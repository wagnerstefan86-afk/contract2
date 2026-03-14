"""Shared enums for the case-based analysis pipeline.

These enums are used across multiple models (AnalysisCase, CaseDocument,
DocumentSection, PolicyRule, ProcessingJob, etc.).
"""

import enum


# ---------------------------------------------------------------------------
# Analysis Case
# ---------------------------------------------------------------------------

class CaseStatus(str, enum.Enum):
    CREATED = "Created"
    INGESTING = "Ingesting"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    FAILED = "Failed"
    ARCHIVED = "Archived"


# ---------------------------------------------------------------------------
# Case Document
# ---------------------------------------------------------------------------

class DocumentType(str, enum.Enum):
    MAIN_CONTRACT = "MAIN_CONTRACT"
    TERMS_AND_CONDITIONS = "TERMS_AND_CONDITIONS"
    SLA = "SLA"
    SERVICE_DESCRIPTION = "SERVICE_DESCRIPTION"
    PRICING = "PRICING"
    DPA = "DPA"
    TOM = "TOM"
    SECURITY_APPENDIX = "SECURITY_APPENDIX"
    SUBPROCESSOR_LIST = "SUBPROCESSOR_LIST"
    EXIT_APPENDIX = "EXIT_APPENDIX"
    ANNEX = "ANNEX"
    OTHER = "OTHER"


class DocumentStatus(str, enum.Enum):
    UPLOADED = "Uploaded"
    PARSING = "Parsing"
    PARSED = "Parsed"
    CLASSIFYING = "Classifying"
    CLASSIFIED = "Classified"
    READY = "Ready"
    FAILED = "Failed"


class ParseStatus(str, enum.Enum):
    PENDING = "Pending"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"


class ClassificationStatus(str, enum.Enum):
    PENDING = "Pending"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"


# ---------------------------------------------------------------------------
# Document Section
# ---------------------------------------------------------------------------

class SectionType(str, enum.Enum):
    HEADING = "HEADING"
    BODY = "BODY"
    TABLE = "TABLE"
    DEFINITION = "DEFINITION"
    FOOTNOTE = "FOOTNOTE"
    ANNEX_REFERENCE = "ANNEX_REFERENCE"
    OTHER = "OTHER"


class SectionRouting(str, enum.Enum):
    """Routing decision from policy scan — determines how a section is processed."""
    IGNORE = "IGNORE"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    POSITIVE_CONTROL = "POSITIVE_CONTROL"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    REVIEWABLE = "REVIEWABLE"


# ---------------------------------------------------------------------------
# Policy Rules
# ---------------------------------------------------------------------------

class RuleType(str, enum.Enum):
    CERTIFICATION = "CERTIFICATION"
    GEO_LOCATION = "GEO_LOCATION"
    STANDARD_CLAUSE = "STANDARD_CLAUSE"
    TOPIC_SUPPRESSION = "TOPIC_SUPPRESSION"
    DOCUMENT_TYPE_RULE = "DOCUMENT_TYPE_RULE"
    OBLIGATION_PATTERN = "OBLIGATION_PATTERN"
    SCOPE_ROUTING = "SCOPE_ROUTING"


class MatchScope(str, enum.Enum):
    SECTION_TEXT = "SECTION_TEXT"
    FINDING_TITLE = "FINDING_TITLE"
    FINDING_CATEGORY = "FINDING_CATEGORY"
    DOCUMENT_TYPE = "DOCUMENT_TYPE"
    NORMALIZED_ENTITY = "NORMALIZED_ENTITY"


class PatternType(str, enum.Enum):
    EXACT = "EXACT"
    REGEX = "REGEX"
    KEYWORD_SET = "KEYWORD_SET"
    NORMALIZED_LOOKUP = "NORMALIZED_LOOKUP"


class RuleAction(str, enum.Enum):
    MARK_POSITIVE_CONTROL = "MARK_POSITIVE_CONTROL"
    SUPPRESS_RISK = "SUPPRESS_RISK"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    REQUIRE_REVIEW = "REQUIRE_REVIEW"
    DOWNGRADE_SEVERITY = "DOWNGRADE_SEVERITY"
    ENRICH_METADATA = "ENRICH_METADATA"


# ---------------------------------------------------------------------------
# Positive Controls
# ---------------------------------------------------------------------------

class ControlType(str, enum.Enum):
    CERTIFICATION = "CERTIFICATION"
    LOCATION = "LOCATION"
    STANDARD_CONTROL = "STANDARD_CONTROL"


class ControlStatus(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    CONDITIONAL = "CONDITIONAL"
    NEEDS_REVIEW = "NEEDS_REVIEW"


# ---------------------------------------------------------------------------
# Finding extensions
# ---------------------------------------------------------------------------

class FindingCategory(str, enum.Enum):
    SECURITY_GOVERNANCE = "SECURITY_GOVERNANCE"
    CERTIFICATION_ASSURANCE = "CERTIFICATION_ASSURANCE"
    AUDIT_RIGHTS = "AUDIT_RIGHTS"
    SUBPROCESSING = "SUBPROCESSING"
    AVAILABILITY_SLA = "AVAILABILITY_SLA"
    INCIDENT_MANAGEMENT = "INCIDENT_MANAGEMENT"
    CHANGE_MANAGEMENT = "CHANGE_MANAGEMENT"
    EXIT_PORTABILITY = "EXIT_PORTABILITY"
    BACKUP_RECOVERY = "BACKUP_RECOVERY"
    BCM_ITSCM = "BCM_ITSCM"
    LIABILITY = "LIABILITY"
    PERFORMANCE_REPORTING = "PERFORMANCE_REPORTING"
    DATA_PROTECTION = "DATA_PROTECTION"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------

class FinalSelectionBasis(str, enum.Enum):
    LLM = "LLM"
    RULE = "RULE"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    HYBRID = "HYBRID"


class EvidenceRole(str, enum.Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    CONFLICTING = "CONFLICTING"
    SUPPORTING = "SUPPORTING"


# ---------------------------------------------------------------------------
# Processing Jobs
# ---------------------------------------------------------------------------

class JobType(str, enum.Enum):
    CASE_INGEST = "CASE_INGEST"
    DOCUMENT_PARSE = "DOCUMENT_PARSE"
    DOCUMENT_CLASSIFY = "DOCUMENT_CLASSIFY"
    SECTION_POLICY_SCAN = "SECTION_POLICY_SCAN"
    SECTION_SCREEN = "SECTION_SCREEN"
    SECTION_EXTRACT = "SECTION_EXTRACT"
    CASE_CLUSTER = "CASE_CLUSTER"
    CASE_CONSOLIDATE = "CASE_CONSOLIDATE"
    CASE_EDITORIAL = "CASE_EDITORIAL"
    CASE_SUMMARIZE = "CASE_SUMMARIZE"


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"
