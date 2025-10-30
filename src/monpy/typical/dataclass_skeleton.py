from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Optional, List

_SENTINEL = object()


class RichChoices:
    # dummy class for the linter - the real enums are in the codebase and passed to/from the functions externally
    pass


@dataclass
class PersonSurface:
    """
    Monday-facing view of a Person.

    Rules
    - mon_ro_*: read-only, computed or protected by the system. Do not set.
    - mon_rw_*: editable fields; safe to set from integrations.
    """

    # --- Read-only fields (do not write from integrations) ---
    # Display name shown on Monday item title.
    mon_ro_item_name: str
    # Human-readable location summary.
    mon_ro_location: str
    # Primary phone number (stringified). May be absent.
    mon_ro_phone: Optional[str]
    # Primary email address.
    mon_ro_email: str
    # GDPR consent date; ISO calendar date.
    mon_ro_gdpr_consent_ts: Optional[date]
    # Current pipeline status (Monday status index).
    mon_ro_pipeline_status_index: Optional[int]
    # Today Hub ID (stable external identifier).
    mon_ro_teid: str
    # Aggregated skills text for quick reference.
    mon_ro_skills_summary: str
    # Language summary (human readable).
    mon_ro_language_summary: str
    # Monday item IDs of jobs where this person is a contact.
    mon_ro_monday_id_contact_for_jobs: List[str]
    # Monday item IDs of organisations where this person is a contact.
    mon_ro_monday_id_contact_for_orgs: List[str]
    # Deep link to edit page in Today Hub.
    mon_ro_edit_link: str
    # Admin change link (may be absent for limited roles).
    mon_ro_admin_link: Optional[str]

    # --- Editable fields (safe to write from integrations) ---
    # Profession/discipline tag IDs on Monday (string IDs).
    mon_rw_monday_profession_ids: List[str]
    # Candidate category (Monday status index).
    mon_rw_monday_candcat_index: Optional[int]


@dataclass
class JobSurface:
    """
    Monday-facing view of a Job Opening.

    Rules
    - mon_ro_*: read-only, computed or protected by the system. Do not set.
    - mon_rw_*: editable fields; safe to set from integrations.
    """

    # --- Read-only fields (do not write from integrations) ---
    # Title (public_title or title fallback).
    mon_ro_title: str
    # Today Hub ID (stable external identifier).
    mon_ro_teid: str
    # Aggregated skills text (read-only summary).
    mon_ro_skills_summary: str
    # Derived status index from most progressed candidate pipeline.
    mon_ro_pipeline_status_index: Optional[int]
    # Location summary for the job.
    mon_ro_location: str
    # Language summary (human readable).
    mon_ro_language_summary: str
    # Monday item IDs for linked client organisations (via project).
    mon_ro_monday_id_client_organisations: List[str]
    # Monday item IDs for candidate people (via pipelines).
    mon_ro_monday_id_candidate_people: List[str]
    # Monday item IDs for all contacts related to the job (client + project roles). None on error.
    mon_ro_monday_contacts_all_ids: Optional[List[str]]
    # Monday user IDs of internal employees assigned to the job.
    mon_ro_monday_assigned_ids: List[str]
    # Monday user IDs of people in the job’s office(s).
    mon_ro_monday_office_people_user_ids: List[str]
    # Public job URL.
    mon_ro_public_link: str
    # Deep link to the job editor in Today Hub.
    mon_ro_edit_link: str
    # Admin change link.
    mon_ro_admin_link: str

    # --- Editable fields (safe to write from integrations) ---
    # Profession/discipline tag IDs on Monday (string IDs).
    mon_rw_monday_profession_ids: List[str]
    # Work mode (Monday status index).
    mon_rw_work_mode_index: Optional[int]
    # Weekly hours category (Monday status index).
    mon_rw_weekly_hours_index: Optional[int]
    # Publication status (Monday status index).
    mon_rw_publication_status_index: Optional[int]


@dataclass
class OrganisationSurface:
    """
    Monday-facing view of an Organisation.

    Rules
    - mon_ro_*: read-only, computed or protected by the system. Do not set.
    - There are no mon_rw fields currently exposed for organisations.
    """

    # --- Read-only fields (do not write from integrations) ---
    # Organisation legal/display name.
    mon_ro_name: str
    # Monday user IDs for internal employees assigned to this organisation.
    mon_ro_monday_assigned_ids: List[str]
    # Monday user IDs of people in offices used by this organisation’s projects.
    mon_ro_monday_office_people_user_ids: List[str]
    # Location summary for the organisation.
    mon_ro_location: str
    # Monday item IDs for all (non-internal) contacts of the organisation. None on error.
    mon_ro_monday_contacts_all_ids: Optional[List[str]]
    # Organisation type (Monday status index).
    mon_ro_monday_type_index: Optional[int]
    # Deep link to the organisation edit page in Today Hub.
    mon_ro_edit_link: str
    # Admin change link.
    mon_ro_admin_link: str


class PipelineStatus(RichChoices):
    APPLIED = ("APPLIED", "Applied", {"weight": 1, "monday_index": 1, "monday_color": "sunset"})
    PROSPECT = ("PROSPECT", "Prospect", {"weight": 2, "monday_index": 2, "monday_color": "egg_yolk"})
    QUALIFIED = ("QUALIFIED", "Qualified", {"weight": 3, "monday_index": 3, "monday_color": "lilac"})
    CV_SENT = ("CV_SENT", "CV Sent", {"weight": 4, "monday_index": 4, "monday_color": "purple"})
    SHORTLISTED = ("SHORTLISTED", "Shortlisted", {"weight": 5, "monday_index": 5, "monday_color": "dark_purple"})
    INTERVIEW = ("INTERVIEW", "Interview", {"weight": 6, "monday_index": 6, "monday_color": "sky"})
    OFFERED = ("OFFERED", "Offered", {"weight": 7, "monday_index": 7, "monday_color": "teal"})
    ACCEPTED = ("ACCEPTED", "Accepted", {"weight": 8, "monday_index": 8, "monday_color": "grass_green"})
    HIRED = ("HIRED", "Hired", {"weight": 9, "terminal": True, "monday_index": 9, "monday_color": "bright_green"})
    REJECTED = ("REJECTED", "Rejected", {"weight": 0, "terminal": True, "monday_index": 10, "monday_color": "stuck_red"})
    UNCLARIFIED = ("UNCLARIFIED", "Unclarified", {"weight": 0, "monday_index": 0, "monday_color": "steel"})


class PublicationStatus(RichChoices):
    TODAY_HOMEPAGE = ("TODAY_HOMEPAGE", "Today Homepage", {"index": 0, "monday_index": 0, "monday_color": "done_green"})
    EXTERNAL_SITES = ("EXTERNAL_SITES", "External Sites", {"index": 1, "monday_index": 1, "monday_color": "working_orange"})
    DO_NOT_POST = ("DO_NOT_POST", "Do not Post", {"index": 2, "monday_index": 2, "monday_color": "stuck_red"})


class WeeklyHours(RichChoices):
    FULL_TIME = ("FULL_TIME", "Full time", {"index": 0, "monday_index": 0, "monday_color": "bright_blue"})
    PART_TIME = ("PART_TIME", "Part time", {"index": 1, "monday_index": 1, "monday_color": "working_orange"})
    MINIJOB = ("MINIJOB", "Minijob", {"index": 2, "monday_index": 2, "monday_color": "stuck_red"})
    FLEXIBLE = ("FLEXIBLE", "Flexible", {"index": 3, "monday_index": 3, "monday_color": "done_green"})
    UNCLARIFIED = ("UNCLARIFIED", "Unclarified", {"index": 4, "monday_index": 4, "monday_color": "steel"})


class WorkMode(RichChoices):
    ONSITE = ("ONSITE", "Onsite", {"index": 0, "monday_index": 0, "monday_color": "stuck_red"})
    HYBRID = ("HYBRID", "Hybrid", {"index": 1, "monday_index": 1, "monday_color": "working_orange"})
    REMOTE = ("REMOTE", "Remote", {"index": 2, "monday_index": 2, "monday_color": "done_green"})
    UNCLARIFIED = ("UNCLARIFIED", "Unclarified", {"index": 3, "monday_index": 3, "monday_color": "steel"})


class ContractorType(RichChoices):
    EMPLOYED = ("EMPLOYED", "Employee", {"index": 0, "monday_index": 0, "monday_color": "done_green"})
    FREELANCE = ("FREELANCE", "Freelancer (self-employed)", {"index": 1, "monday_index": 1, "monday_color": "teal"})
    AGENCY = ("AGENCY", "Via partner agency", {"index": 2, "monday_index": 2, "monday_color": "working_orange"})
    UNCLARIFIED = ("UNCLARIFIED", "Unclarified", {"index": 3, "monday_index": 3, "monday_color": "american_gray"})


class CandidateCategory(RichChoices):
    KEYSELLING = ("KEYSELLING", "Keyselling", {"index": 0, "monday_index": 0, "monday_color": "done_green"})
    RESELLING = ("RESELLING", "Reselling", {"index": 1, "monday_index": 2, "monday_color": "purple"})
    GOOD = ("GOOD", "Good", {"index": 2, "monday_index": 3, "monday_color": "bright_blue"})
    ACCEPTABLE = ("ACCEPTABLE", "Acceptable", {"index": 3, "monday_index": 4, "monday_color": "working_orange"})
    POOR = ("POOR", "Poor", {"index": 4, "monday_index": 5, "monday_color": "stuck_red"})
    UNCLARIFIED = ("UNCLARIFIED", "Unclarified", {"index": 5, "monday_index": 1, "monday_color": "steel"})


class OrgType(RichChoices):
    PROSPECTIVE = ("PROSPECTIVE", "Prospective", {"index": 0, "monday_index": 0, "monday_color": "purple"})
    CLIENT = ("CLIENT", "Client", {"index": 1, "monday_index": 1, "monday_color": "done_green"})
    PARTNER = ("PARTNER", "Partner", {"index": 2, "monday_index": 3, "monday_color": "working_orange"})
    INTERNAL = ("INTERNAL", "Internal", {"index": 3, "monday_index": 4, "monday_color": "dark_blue"})
    CLIENT_AND_PARTNER = ("CLIENT_AND_PARTNER", "Client and Partner", {"index": 4, "monday_index": 2, "monday_color": "sky"})
    UNCLARIFIED = ("UNCLARIFIED", "Unclarified", {"index": 5, "monday_index": 5, "monday_color": "american_gray"})
    UNSUCCESSFUL = ("UNSUCCESSFUL", "Unsuccessful", {"index": 6, "monday_index": 6, "monday_color": "stuck_red"})


def _enum_attr(member: object, key: str, default: Any = None) -> Any:
    """
    Safely read an enum member attribute:
    - direct attribute (e.g. monday_index)
    - member.attrs[...] (RichChoices/WeightedChoices)
    - special-case 'label'
    """
    if key == "label":
        return getattr(member, "label", default)
    try:
        return getattr(member, key)
    except Exception:
        pass
    attrs = getattr(member, "attrs", None)
    if isinstance(attrs, dict):
        return attrs.get(key, default)
    return default

def print_enum_segments(enum_cls, keys: Iterable[str] = ("label", "monday_index", "monday_color")) -> None:
    """
    Print each member of enum_cls in declaration order with selected attrs.
    Works with Django TextChoices/WeightedChoices/RichChoices.
    """
    for m in enum_cls:
        parts = [f"{enum_cls.__name__}.{m.name}"]
        for k in keys:
            v = _enum_attr(m, k, None)
            parts.append(f"{k}={v!r}")
        print(", ".join(parts))

def find_enum_member_by_attr(enum_cls, attr: str, value) -> Optional[object]:
    """
    Return the first member where attribute 'attr' (or member.attrs[attr]) equals 'value'.
    Accepts 'label' as a pseudo-attribute.
    """
    for m in enum_cls:
        v = _enum_attr(m, attr, _SENTINEL)
        if v is not _SENTINEL and (v == value or str(v) == str(value)):
            return m
    return None
