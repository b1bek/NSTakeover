import json
import shutil
import subprocess
import time
from typing import List, Optional, Sequence, Set

from .commands import run_command
from .dns import parse_azure_ns_numbers_from_text
from .output import YELLOW, colorize, emit


DEFAULT_REGIONS = [
    "australiacentral",
    "australiacentral2",
    "australiaeast",
    "australiasoutheast",
    "brazilsouth",
    "brazilsoutheast",
    "canadacentral",
    "canadaeast",
    "centralindia",
    "centralus",
    "centraluseuap",
    "eastasia",
    "eastus",
    "eastus2",
    "eastus2euap",
    "francecentral",
    "francesouth",
    "germanynorth",
    "germanywestcentral",
    "japaneast",
    "japanwest",
    "koreacentral",
    "koreasouth",
    "northcentralus",
    "northeurope",
    "norwayeast",
    "norwaywest",
    "qatarcentral",
    "southafricanorth",
    "southafricawest",
    "southcentralus",
    "southeastasia",
    "southindia",
    "swedencentral",
    "swedensouth",
    "switzerlandnorth",
    "switzerlandwest",
    "uaecentral",
    "uaenorth",
    "uksouth",
    "ukwest",
    "westcentralus",
    "westeurope",
    "westindia",
    "westus",
    "westus2",
    "westus3",
    "asia",
    "asiapacific",
    "australia",
    "brazil",
    "canada",
    "devfabric",
    "europe",
    "global",
    "india",
    "japan",
    "northwestus",
    "uk",
    "france",
    "germany",
    "switzerland",
    "korea",
    "norway",
    "uae",
    "southafrica",
    "unitedstates",
    "unitedstateseuap",
    "westuspartner",
    "singapore",
    "eastusslv",
    "israelcentral",
    "italynorth",
    "malaysiasouth",
    "polandcentral",
    "taiwannorth",
    "taiwannorthwest",
]


class NSTakeoverError(Exception):
    pass


def run_az(args: Sequence[str], timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return run_command(["az", *args], timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        command = "az " + " ".join(args)
        raise NSTakeoverError(f"command timed out after {timeout}s: {command}") from exc


def check_azure_cli() -> None:
    if not shutil.which("az"):
        raise NSTakeoverError(
            "az cli not installed. Install it from "
            "https://learn.microsoft.com/en-us/cli/azure/install-azure-cli"
        )

    account = run_az(["account", "show"], timeout=30)
    if account.returncode != 0:
        raise NSTakeoverError("az cli not logged in. Use command: az login")


def ensure_network_provider_registered(timeout: int = 600, interval: int = 15) -> None:
    deadline = time.monotonic() + timeout
    registration_started = False

    while True:
        output = run_az(
            [
                "provider",
                "show",
                "--namespace",
                "Microsoft.Network",
                "--query",
                "registrationState",
                "--output",
                "tsv",
            ],
            timeout=60,
        )
        state = output.stdout.strip()

        if output.returncode == 0 and state == "Registered":
            return

        if not registration_started:
            emit(f"Registering Microsoft.Network provider; current state: {state or 'unknown'}")
            register = run_az(
                ["provider", "register", "--namespace", "Microsoft.Network"],
                timeout=60,
            )
            if register.returncode != 0:
                raise NSTakeoverError(
                    "failed to start Microsoft.Network provider registration: "
                    f"{register.stderr.strip()}"
                )
            registration_started = True

        if time.monotonic() >= deadline:
            raise NSTakeoverError(
                "Microsoft.Network provider registration did not complete before timeout"
            )

        emit("Waiting for Microsoft.Network provider registration")
        time.sleep(interval)


def get_azure_regions(selected_regions: Optional[List[str]]) -> List[str]:
    if selected_regions:
        return selected_regions

    locations = run_az(
        [
            "account",
            "list-locations",
            "--query",
            "[?metadata.regionType=='Physical'].name",
            "-o",
            "json",
        ]
    )
    if locations.returncode == 0:
        try:
            regions = json.loads(locations.stdout)
            if isinstance(regions, list) and regions:
                return [
                    str(region)
                    for region in regions
                    if not is_non_resource_group_location(str(region))
                ]
        except json.JSONDecodeError:
            pass

    emit(colorize("Unable to fetch Azure locations; using bundled fallback list.", YELLOW))
    return DEFAULT_REGIONS


def is_non_resource_group_location(region: str) -> bool:
    return region.endswith("euap") or region.endswith("stage") or region.endswith("stg")


def create_resource_group(group_name: str, region: str) -> None:
    output = run_az(
        ["group", "create", "--location", region, "--name", group_name, "--output", "none"],
        timeout=180,
    )
    if output.returncode != 0:
        raise NSTakeoverError(
            f"failed to create resource group {group_name}: {output.stderr.strip()}"
        )


def create_dns_zone(domain: str, group_name: str) -> Set[str]:
    output = run_az(
        [
            "network",
            "dns",
            "zone",
            "create",
            "--name",
            domain,
            "--resource-group",
            group_name,
            "--output",
            "json",
        ],
        timeout=300,
    )
    if output.returncode != 0:
        raise NSTakeoverError(
            f"failed to create DNS zone in {group_name}: {output.stderr.strip()}"
        )

    try:
        zone = json.loads(output.stdout)
    except json.JSONDecodeError as exc:
        raise NSTakeoverError(f"Azure returned invalid JSON for {group_name}") from exc

    name_servers = zone.get("nameServers", [])
    if not isinstance(name_servers, list):
        raise NSTakeoverError(f"Azure response did not include nameServers for {group_name}")

    numbers = parse_azure_ns_numbers_from_text("\n".join(str(ns) for ns in name_servers))
    if not numbers:
        raise NSTakeoverError(f"could not parse Azure nameservers for {group_name}")

    return numbers


def delete_resource_group(group_name: str) -> None:
    output = run_az(
        ["group", "delete", "--name", group_name, "--no-wait", "--yes"],
        timeout=60,
    )
    if output.returncode != 0:
        emit(
            colorize(
                f"Warning: failed to delete resource group {group_name}: "
                f"{output.stderr.strip()}",
                YELLOW,
            )
        )
