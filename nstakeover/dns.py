import ipaddress
import json
import re
import shutil
import subprocess
from typing import Any, Iterable, Optional, Set, Tuple
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .commands import run_command


AZURE_NS_RE = re.compile(
    r"\bns[1-4]-(\d+)\.azure-dns\.(?:com|net|org|info)\.?", re.IGNORECASE
)
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]"
    r"(?:[a-z0-9-]{0,61}[a-z0-9])?$",
    re.IGNORECASE,
)
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
BRACKETED_IP_RE = re.compile(r"\[([0-9a-fA-F:.]+)\]")


class ValidationError(ValueError):
    pass


def normalize_domain(value: str) -> str:
    domain = value.strip().rstrip(".").lower()
    if not DOMAIN_RE.fullmatch(domain):
        raise ValidationError(f"invalid domain: {value}")
    return domain


def normalize_ns_number(value: str) -> str:
    number = value.strip()
    if not re.fullmatch(r"\d+", number):
        raise ValidationError(f"invalid Azure nameserver number: {value}")
    return str(int(number))


def parse_ns_number_list(values: Iterable[str]) -> Set[str]:
    numbers = set()
    for value in values:
        for item in value.split(","):
            item = item.strip()
            if item:
                numbers.add(normalize_ns_number(item))
    return numbers


def parse_azure_ns_numbers_from_text(text: str) -> Set[str]:
    return {normalize_ns_number(match.group(1)) for match in AZURE_NS_RE.finditer(text)}


def extract_ips_from_text(text: str) -> Set[str]:
    ips = set()

    for match in IPV4_RE.finditer(text):
        try:
            ips.add(str(ipaddress.ip_address(match.group(0))))
        except ValueError:
            pass

    for match in BRACKETED_IP_RE.finditer(text):
        try:
            ips.add(str(ipaddress.ip_address(match.group(1))))
        except ValueError:
            pass

    return ips


def doh_query(name: str, record_type: str, timeout: int = 10) -> Optional[Any]:
    query = urlencode({"name": name, "type": record_type})
    request = Request(
        f"https://dns.google/resolve?{query}",
        headers={"accept": "application/dns-json", "user-agent": "NSTakeover/1.0"},
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (json.JSONDecodeError, TimeoutError, URLError, OSError):
        return None


def detect_ns_numbers_with_dig(domain: str) -> Set[str]:
    if not shutil.which("dig"):
        return set()

    commands = [
        ["dig", "+short", "NS", domain],
        ["dig", "+trace", domain, "NS"],
    ]

    for command in commands:
        try:
            output = run_command(command, timeout=25)
        except (subprocess.TimeoutExpired, OSError):
            continue

        numbers = parse_azure_ns_numbers_from_text(f"{output.stdout}\n{output.stderr}")
        if numbers:
            return numbers

    return set()


def detect_ns_numbers_with_google_doh(domain: str) -> Set[str]:
    payload = doh_query(domain, "NS")
    if payload is None:
        return set()

    payload_text = json.dumps(payload)
    numbers = parse_azure_ns_numbers_from_text(payload_text)
    if numbers:
        return numbers

    for ip in extract_ips_from_text(payload_text):
        ptr_payload = doh_query(ipaddress.ip_address(ip).reverse_pointer, "PTR")
        if ptr_payload is not None:
            numbers.update(parse_azure_ns_numbers_from_text(json.dumps(ptr_payload)))

    return numbers


def detect_target_ns_numbers(domain: str) -> Tuple[Set[str], str]:
    dig_numbers = detect_ns_numbers_with_dig(domain)
    if dig_numbers:
        return dig_numbers, "dig"

    doh_numbers = detect_ns_numbers_with_google_doh(domain)
    if doh_numbers:
        return doh_numbers, "Google DNS-over-HTTPS"

    return set(), "none"
