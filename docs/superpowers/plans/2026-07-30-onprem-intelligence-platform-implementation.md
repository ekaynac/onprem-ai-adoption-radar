# On-Prem Intelligence Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the seed-first radar and dense Jinja dashboard with a provenance-first, continuously updated on-prem intelligence core and React Architect Workspace while preserving existing deterministic scoring, capacity, history, CLI, MCP, feeds, and static publishing behavior.

**Architecture:** A new `radar.intelligence` package owns canonical contracts, SQLAlchemy-backed repositories, evidence/lifecycle services, scheduled jobs, and versioned application queries. Existing collectors and deterministic engines are adapted behind those contracts before FastAPI, MCP, feeds, and the React application cut over. SQLite is the default store; PostgreSQL is optional through the same repository implementation.

**Tech Stack:** Python 3.12, Pydantic 2, FastAPI, SQLAlchemy 2, Alembic, APScheduler, httpx, pytest, React, TypeScript, Vite, React Router, TanStack Query, Vitest, Testing Library, Playwright, axe-core.

## Global Constraints

- At least 95% of qualifying official major-model releases become publicly visible as **Detected** within two hours of the first observable official artifact or trusted registry record.
- Lifecycle order is `Detected → Verified → Qualified → Recommended`; public Detected records require an official source or trusted registry.
- No Verified, Qualified, or Recommended value may exist without qualifying claim-level provenance.
- Model categories are text/reasoning, multimodal, embedding/reranking, speech/audio, image/video, and vision/OCR/document.
- SQLite is the default local database; PostgreSQL is optional through identical repository interfaces.
- The product has one unrestricted local user role, no login, and multiple logical workspaces that are not security boundaries.
- The public static edition is read-only and contains no workspace-specific data or mutation controls.
- LLMs may extract candidate claims but may not verify facts, resolve conflicts, establish lifecycle state, or assign adoption rings.
- The default deployment requires no Redis or standalone queue.
- Existing YAML and append-only JSONL sources remain intact until migration rehearsal and shadow parity pass.
- The React application, REST API, MCP, feeds, CLI adapters, and static export read the same application services.

---

## File and module map

### New backend modules

- `src/radar/intelligence/contracts.py` — canonical enums and immutable Pydantic contracts.
- `src/radar/intelligence/database.py` — SQLAlchemy engine/session construction for SQLite and PostgreSQL.
- `src/radar/intelligence/schema.py` — normalized ORM tables and uniqueness/index constraints.
- `src/radar/intelligence/repositories.py` — repository protocols and SQLAlchemy implementations.
- `src/radar/intelligence/events.py` — versioned event envelope and append-only event service.
- `src/radar/intelligence/identity.py` — publisher/release identity normalization and alias resolution.
- `src/radar/intelligence/lifecycle.py` — lifecycle transition rules and provenance gates.
- `src/radar/intelligence/verification.py` — automatic verification with review exceptions.
- `src/radar/intelligence/qualification.py` — category dispatch and common qualification result.
- `src/radar/intelligence/platforms.py` — version-aware platform compatibility service.
- `src/radar/intelligence/workspaces.py` — workspace, estate, workload, and policy services.
- `src/radar/intelligence/recommendations.py` — public and workspace-adjusted recommendation projection.
- `src/radar/intelligence/migration.py` — idempotent import of YAML, JSONL, and latest run projections.
- `src/radar/intelligence/jobs.py` — job records, leases, idempotency, and orchestration.
- `src/radar/intelligence/scheduler.py` — built-in APScheduler entry point.
- `src/radar/intelligence/sources/base.py` — source adapter protocol and normalized observations.
- `src/radar/intelligence/sources/huggingface.py` — six-category HF discovery and artifact collection.
- `src/radar/intelligence/sources/github.py` — official organization/release collection.
- `src/radar/intelligence/sources/feeds.py` — RSS/Atom/announcement collection.
- `src/radar/intelligence/sources/registries.py` — ModelScope, Ollama, package, and container registry collection.
- `src/radar/intelligence/sources/evidence.py` — benchmark, paper, security, and license evidence collection.
- `src/radar/intelligence/sources/registry.py` — configured adapter construction.
- `src/radar/intelligence/services/catalog.py` — catalog/search/detail queries.
- `src/radar/intelligence/services/releases.py` — release stream and lifecycle queries.
- `src/radar/intelligence/services/deployments.py` — compatibility/capacity façade.
- `src/radar/intelligence/services/operations.py` — review, source health, and job status queries.
- `src/radar/api/app.py` — versioned API application factory and SPA/static mounting.
- `src/radar/api/dependencies.py` — database/service/workspace dependency construction.
- `src/radar/api/routes/*.py` — resource-specific `/api/v1` routers.
- `src/radar/mcp_server/intelligence_queries.py` — context-efficient MCP query façade.
- `src/radar/reports/intelligence_feeds.py` — release/lifecycle/compatibility feed rendering.
- `src/radar/web/intelligence_snapshot.py` — public read-only snapshot generation.

### New frontend

- `frontend/package.json`, `frontend/package-lock.json` — scripts and locked dependencies.
- `frontend/vite.config.ts`, `frontend/tsconfig*.json` — build and type configuration.
- `frontend/playwright.config.ts` — browser workflow and visual verification.
- `frontend/src/main.tsx` — browser entry point.
- `frontend/src/app/App.tsx` — route tree and application providers.
- `frontend/src/app/shell/*` — Architect Workspace navigation, top bar, and responsive shell.
- `frontend/src/api/client.ts` — generated-client wrapper and workspace header/query handling.
- `frontend/src/api/generated/*` — OpenAPI-generated types/client; never hand-edited.
- `frontend/src/design/*` — Mega tokens, shared CSS, status/ring components.
- `frontend/src/features/overview/*` — Balanced Decisions overview.
- `frontend/src/features/releases/*` — discovery/release stream and lifecycle.
- `frontend/src/features/catalog/*` — model/platform/hardware/research search and detail.
- `frontend/src/features/compare/*` — comparison workspace.
- `frontend/src/features/planner/*` — deployment planner.
- `frontend/src/features/workspaces/*` — workspace configuration and switcher.
- `frontend/src/features/operations/*` — review queue, source health, jobs, feeds, MCP/API.
- `frontend/tests/*` — shared fixtures, accessibility, and route-level tests.
- `frontend/e2e/*` — Playwright workflows and visual baselines.

### Existing integration points

- `src/radar/web/app.py` — compatibility redirects and SPA mount after cutover.
- `src/radar/web/static_site.py` — legacy export retained until snapshot parity.
- `src/radar/mcp_server/server.py` — register new tools while retaining old names.
- `src/radar/cli.py` — migration, intelligence scan, scheduler, and export commands.
- `pyproject.toml` — backend dependencies and package data.
- `.github/workflows/publish.yml` — two-hour discovery, daily qualification, and React static export.

---

### Task 1: Canonical intelligence contracts

**Files:**
- Create: `src/radar/intelligence/__init__.py`
- Create: `src/radar/intelligence/contracts.py`
- Test: `tests/intelligence/test_contracts.py`

**Interfaces:**
- Produces: `LifecycleState`, `ModelCategory`, `ReleaseLane`, `EvidenceStrength`, `ClaimState`, `ClaimFreshness`, `SupportStatus`, `EvidenceLevel`, `Publisher`, `ProductFamily`, `Release`, `Artifact`, `Claim`, `EvidenceObservation`, `CompatibilityAssertion`, `Qualification`, `Recommendation`, `LifecycleTransition`, `ReviewException`.
- Consumes: existing `radar.models.Ring` for recommendation rings.

- [ ] **Step 1: Write failing contract and validation tests**

```python
# tests/intelligence/test_contracts.py
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from radar.intelligence.contracts import (
    Claim,
    ClaimState,
    EvidenceObservation,
    EvidenceStrength,
    LifecycleState,
    ModelCategory,
    Release,
    ReleaseLane,
)


NOW = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)


def test_detected_release_requires_public_discovery_source() -> None:
    with pytest.raises(ValidationError, match="official or trusted"):
        Release(
            id="release:kimi-k3",
            family_id="family:kimi",
            publisher_id="publisher:moonshot-ai",
            name="Kimi K3",
            category=ModelCategory.MULTIMODAL,
            lane=ReleaseLane.DEPLOYABLE,
            lifecycle=LifecycleState.DETECTED,
            first_observed_at=NOW,
            discovery_evidence_strength=EvidenceStrength.COMMUNITY,
        )


def test_verified_claim_requires_evidence_ids() -> None:
    with pytest.raises(ValidationError, match="evidence"):
        Claim(
            id="claim:kimi-k3:context",
            subject_id="release:kimi-k3",
            predicate="context_tokens",
            value=1_048_576,
            state=ClaimState.VERIFIED,
            observed_at=NOW,
            evidence_ids=[],
        )


def test_evidence_observation_is_immutable() -> None:
    evidence = EvidenceObservation(
        id="evidence:hf:kimi-k3:config",
        source_url="https://huggingface.co/moonshotai/Kimi-K3/raw/main/config.json",
        strength=EvidenceStrength.OFFICIAL_ARTIFACT,
        retrieved_at=NOW,
        checksum="sha256:abc",
        extractor_version="hf-config-v1",
    )
    with pytest.raises(ValidationError):
        evidence.checksum = "sha256:changed"
```

- [ ] **Step 2: Run the contract tests and verify they fail**

Run: `uv run pytest tests/intelligence/test_contracts.py -q`  
Expected: FAIL because `radar.intelligence.contracts` does not exist.

- [ ] **Step 3: Implement the canonical enums and core validators**

```python
# src/radar/intelligence/contracts.py
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from radar.models import Ring


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LifecycleState(StrEnum):
    DETECTED = "detected"
    VERIFIED = "verified"
    QUALIFIED = "qualified"
    RECOMMENDED = "recommended"


class ModelCategory(StrEnum):
    TEXT_REASONING = "text_reasoning"
    MULTIMODAL = "multimodal"
    EMBEDDING_RERANKING = "embedding_reranking"
    SPEECH_AUDIO = "speech_audio"
    IMAGE_VIDEO = "image_video"
    VISION_DOCUMENT = "vision_document"


class ReleaseLane(StrEnum):
    DEPLOYABLE = "deployable_onprem"
    ADJACENT = "onprem_adjacent"
    MARKET_REFERENCE = "market_reference"


class EvidenceStrength(StrEnum):
    OFFICIAL_ARTIFACT = "official_artifact"
    OFFICIAL_DOCUMENTATION = "official_documentation"
    OFFICIAL_REPOSITORY = "official_repository"
    OFFICIAL_ANNOUNCEMENT = "official_announcement"
    TRUSTED_REGISTRY = "trusted_registry"
    BENCHMARK_MAINTAINER = "benchmark_maintainer"
    AGGREGATOR = "aggregator"
    COMMUNITY = "community"


PUBLIC_DISCOVERY_STRENGTHS = {
    EvidenceStrength.OFFICIAL_ARTIFACT,
    EvidenceStrength.OFFICIAL_DOCUMENTATION,
    EvidenceStrength.OFFICIAL_REPOSITORY,
    EvidenceStrength.OFFICIAL_ANNOUNCEMENT,
    EvidenceStrength.TRUSTED_REGISTRY,
}


class ClaimState(StrEnum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    CONFLICTING = "conflicting"
    STALE = "stale"
    REJECTED = "rejected"


class ClaimFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"


class SupportStatus(StrEnum):
    YES = "yes"
    PARTIAL = "partial"
    NO = "no"
    UNKNOWN = "unknown"


class EvidenceLevel(StrEnum):
    DOCUMENTED = "documented"
    TESTED = "tested"
    INFERRED = "inferred"


class Release(FrozenModel):
    id: str
    family_id: str
    publisher_id: str
    name: str
    category: ModelCategory
    lane: ReleaseLane
    lifecycle: LifecycleState
    first_observed_at: datetime
    discovery_evidence_strength: EvidenceStrength

    @model_validator(mode="after")
    def validate_public_detection(self) -> Release:
        if (
            self.lifecycle == LifecycleState.DETECTED
            and self.discovery_evidence_strength not in PUBLIC_DISCOVERY_STRENGTHS
        ):
            raise ValueError("Detected releases require official or trusted evidence")
        return self


class Claim(FrozenModel):
    id: str
    subject_id: str
    predicate: str
    value: Any
    state: ClaimState
    observed_at: datetime
    evidence_ids: list[str] = Field(default_factory=list)
    unit: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    supersedes_claim_id: str | None = None

    @model_validator(mode="after")
    def validate_verified_evidence(self) -> Claim:
        if self.state == ClaimState.VERIFIED and not self.evidence_ids:
            raise ValueError("Verified claims require evidence")
        return self


class EvidenceObservation(FrozenModel):
    id: str
    source_url: str
    strength: EvidenceStrength
    retrieved_at: datetime
    checksum: str
    extractor_version: str
    raw_snapshot_path: str | None = None


class Publisher(FrozenModel):
    id: str
    name: str
    official_domains: list[str]
    official_accounts: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)


class ProductFamily(FrozenModel):
    id: str
    publisher_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)


class Artifact(FrozenModel):
    id: str
    release_id: str
    kind: str
    url: str
    checksum: str | None = None
    accessible: bool


class CompatibilityAssertion(FrozenModel):
    id: str
    release_id: str
    platform_id: str
    platform_version: str
    feature: str
    support: SupportStatus
    evidence_level: EvidenceLevel
    evidence_ids: list[str]
    hardware_scope: list[str] = Field(default_factory=list)


class Qualification(FrozenModel):
    release_id: str
    qualified: bool
    category: ModelCategory
    reasons: list[str]
    assumptions: list[str]
    evidence_ids: list[str]


class Recommendation(FrozenModel):
    release_id: str
    workspace_id: str | None
    ring: Ring
    score: float
    reasons: list[str]
    assumptions: list[str]
    evidence_ids: list[str]
    computation_version: str


class LifecycleTransition(FrozenModel):
    release_id: str
    from_state: LifecycleState | None
    to_state: LifecycleState
    observed_at: datetime
    reason: str
    evidence_ids: list[str]


class ReviewException(FrozenModel):
    id: str
    subject_id: str
    code: str
    message: str
    evidence_ids: list[str]
    opened_at: datetime
    resolved_at: datetime | None = None
```

- [ ] **Step 4: Run contracts, lint, and type checks**

Run:

```bash
uv run pytest tests/intelligence/test_contracts.py -q
uv run ruff check src/radar/intelligence/contracts.py tests/intelligence/test_contracts.py
uv run mypy src/radar/intelligence/contracts.py
```

Expected: all commands pass.

- [ ] **Step 5: Commit the contract boundary**

```bash
git add src/radar/intelligence tests/intelligence/test_contracts.py
git commit -m "feat(intelligence): add canonical domain contracts"
```

---

### Task 2: SQLAlchemy storage and repository boundary

**Files:**
- Modify: `pyproject.toml`
- Create: `src/radar/intelligence/database.py`
- Create: `src/radar/intelligence/schema.py`
- Create: `src/radar/intelligence/repositories.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/versions/20260730_0001_intelligence_core.py`
- Test: `tests/intelligence/test_repositories.py`

**Interfaces:**
- Consumes: Task 1 canonical contracts.
- Produces: `Database`, `IntelligenceRepository`, `SqlAlchemyIntelligenceRepository`, `RepositoryConflict`.

- [ ] **Step 1: Add failing repository round-trip and append-only tests**

```python
# tests/intelligence/test_repositories.py
from datetime import UTC, datetime

from radar.intelligence.contracts import EvidenceObservation, EvidenceStrength
from radar.intelligence.database import Database
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository


def test_evidence_is_append_only_and_idempotent(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'intelligence.db'}")
    database.create_schema()
    repo = SqlAlchemyIntelligenceRepository(database)
    evidence = EvidenceObservation(
        id="evidence:one",
        source_url="https://example.com/config.json",
        strength=EvidenceStrength.OFFICIAL_ARTIFACT,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
        checksum="sha256:one",
        extractor_version="test-v1",
    )

    repo.append_evidence(evidence)
    repo.append_evidence(evidence)

    assert repo.get_evidence("evidence:one") == evidence
    assert repo.count_evidence() == 1


def test_sqlite_enables_foreign_keys(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'intelligence.db'}")
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL is not configured",
)
def test_postgres_implements_same_evidence_contract() -> None:
    database = Database(os.environ["TEST_POSTGRES_URL"])
    database.create_schema()
    repo = SqlAlchemyIntelligenceRepository(database)
    evidence = make_evidence("evidence:postgres")
    repo.append_evidence(evidence)
    assert repo.get_evidence(evidence.id) == evidence
```

- [ ] **Step 2: Run repository tests and verify they fail**

Run: `uv run pytest tests/intelligence/test_repositories.py -q`  
Expected: FAIL because database and repository modules do not exist.

- [ ] **Step 3: Add persistence dependencies**

Add to `pyproject.toml` core dependencies:

```toml
"alembic>=1.14.0",
"apscheduler>=3.11.0",
"sqlalchemy>=2.0.36",
```

Add an optional dependency group:

```toml
postgres = ["psycopg[binary]>=3.2.0"]
```

Run: `uv lock`

- [ ] **Step 4: Implement database/session construction and ORM schema**

```python
# src/radar/intelligence/database.py
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from radar.intelligence.schema import Base


class Database:
    def __init__(self, url: str):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, future=True, connect_args=connect_args)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._enable_sqlite_foreign_keys)

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine) as session:
            with session.begin():
                yield session
```

```python
# src/radar/intelligence/schema.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EvidenceRow(Base):
    __tablename__ = "intelligence_evidence"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_url: Mapped[str] = mapped_column(Text)
    strength: Mapped[str] = mapped_column(String(40), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    checksum: Mapped[str] = mapped_column(String(80))
    extractor_version: Mapped[str] = mapped_column(String(80))
    raw_snapshot_path: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("source_url", "checksum", name="uq_evidence_source_hash"),)


class ClaimRow(Base):
    __tablename__ = "intelligence_claims"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(255), index=True)
    predicate: Mapped[str] = mapped_column(String(100), index=True)
    value: Mapped[object] = mapped_column(JSON)
    unit: Mapped[str | None] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(24), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("intelligence_claims.id")
    )

    __table_args__ = (
        Index("ix_claim_current", "subject_id", "predicate", "state", "observed_at"),
    )


class ClaimEvidenceRow(Base):
    __tablename__ = "intelligence_claim_evidence"

    claim_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_claims.id"), primary_key=True
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("intelligence_evidence.id"), primary_key=True
    )
```

The migration must create additional normalized tables matching Task 1
contracts: publishers, families, releases, artifacts, platform releases,
compatibility assertions, qualifications, recommendations, lifecycle events,
review exceptions, events, workspaces, estates, workloads, policies,
watchlists, jobs, source health, webhook subscriptions, and webhook attempts.
Every foreign key and uniqueness rule must be represented in both
`schema.py` and the Alembic revision.

- [ ] **Step 5: Implement repository protocol and evidence methods**

```python
# src/radar/intelligence/repositories.py
from __future__ import annotations

from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from radar.intelligence.contracts import EvidenceObservation, EvidenceStrength
from radar.intelligence.database import Database
from radar.intelligence.schema import EvidenceRow


class RepositoryConflict(ValueError):
    pass


class IntelligenceRepository(Protocol):
    def append_evidence(self, evidence: EvidenceObservation) -> None: ...
    def get_evidence(self, evidence_id: str) -> EvidenceObservation | None: ...
    def count_evidence(self) -> int: ...


class SqlAlchemyIntelligenceRepository:
    def __init__(self, database: Database):
        self.database = database

    def append_evidence(self, evidence: EvidenceObservation) -> None:
        with self.database.session() as session:
            existing = session.get(EvidenceRow, evidence.id)
            if existing:
                if existing.checksum != evidence.checksum:
                    raise RepositoryConflict(f"Evidence id changed: {evidence.id}")
                return
            session.add(EvidenceRow(**evidence.model_dump(mode="python")))

    def get_evidence(self, evidence_id: str) -> EvidenceObservation | None:
        with self.database.session() as session:
            row = session.get(EvidenceRow, evidence_id)
            if row is None:
                return None
            return EvidenceObservation(
                id=row.id,
                source_url=row.source_url,
                strength=EvidenceStrength(row.strength),
                retrieved_at=row.retrieved_at,
                checksum=row.checksum,
                extractor_version=row.extractor_version,
                raw_snapshot_path=row.raw_snapshot_path,
            )

    def count_evidence(self) -> int:
        with self.database.session() as session:
            return session.scalar(select(func.count()).select_from(EvidenceRow)) or 0
```

Complete the repository with explicit append/upsert/query methods for every
table. Append-only methods reject changed payloads under an existing ID;
current-projection methods use scoped unique constraints and deterministic
upserts.

- [ ] **Step 6: Run migration and repository verification**

Run:

```bash
uv run alembic upgrade head
uv run pytest tests/intelligence/test_repositories.py -q
uv run ruff check src/radar/intelligence tests/intelligence migrations
uv run mypy src/radar/intelligence
```

Expected: schema upgrade succeeds and all verification passes.

- [ ] **Step 7: Commit persistence**

```bash
git add pyproject.toml uv.lock alembic.ini migrations src/radar/intelligence tests/intelligence
git commit -m "feat(intelligence): add canonical persistence"
```

---

### Task 3: Legacy importer and shadow projections

**Files:**
- Create: `src/radar/intelligence/migration.py`
- Create: `src/radar/intelligence/shadow.py`
- Modify: `src/radar/cli.py`
- Test: `tests/intelligence/test_migration.py`
- Test: `tests/intelligence/test_shadow.py`

**Interfaces:**
- Consumes: Task 2 repository; `load_model_seed`, `load_platform_matrix`, existing JSONL readers, and `RunStore`.
- Produces: `MigrationReport`, `import_legacy_state(root, repository)`, `ShadowReport`, `compare_legacy_projection(root, services)`.

- [ ] **Step 1: Write failing idempotent-import tests**

```python
# tests/intelligence/test_migration.py
from pathlib import Path

from radar.init_project import initialize_project
from radar.intelligence.database import Database
from radar.intelligence.migration import import_legacy_state
from radar.intelligence.repositories import SqlAlchemyIntelligenceRepository


def test_import_is_idempotent_and_preserves_model_count(tmp_path: Path) -> None:
    initialize_project(tmp_path)
    database = Database(f"sqlite:///{tmp_path / 'data' / 'intelligence.db'}")
    database.create_schema()
    repository = SqlAlchemyIntelligenceRepository(database)

    first = import_legacy_state(tmp_path, repository)
    second = import_legacy_state(tmp_path, repository)

    assert first.models_imported > 0
    assert second.models_imported == 0
    assert second.already_present == first.models_imported + first.platforms_imported
```

- [ ] **Step 2: Run migration tests and verify they fail**

Run: `uv run pytest tests/intelligence/test_migration.py -q`  
Expected: FAIL because the migration service does not exist.

- [ ] **Step 3: Implement deterministic import and report**

```python
# src/radar/intelligence/migration.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from radar.mcp_server.model_queries import load_platform_entries
from radar.models_radar.seed import load_model_seed


@dataclass(frozen=True)
class MigrationReport:
    models_imported: int
    platforms_imported: int
    history_events_imported: int
    already_present: int
    warnings: tuple[str, ...]


def import_legacy_state(root: Path, repository) -> MigrationReport:
    model_path = root / "config" / "model-seed.yaml"
    models = load_model_seed(model_path)
    platforms = load_platform_entries(root)
    models_imported = 0
    platforms_imported = 0
    already_present = 0

    for seed in models:
        created = repository.import_legacy_model_seed(seed)
        models_imported += int(created)
        already_present += int(not created)
    for platform in platforms:
        created = repository.import_legacy_platform_seed(platform)
        platforms_imported += int(created)
        already_present += int(not created)

    history_count, warnings = repository.import_legacy_logs(root / "data")
    return MigrationReport(
        models_imported=models_imported,
        platforms_imported=platforms_imported,
        history_events_imported=history_count,
        already_present=already_present,
        warnings=tuple(warnings),
    )
```

Implement stable legacy IDs (`legacy:model:<seed-id>`,
`legacy:platform:<platform-id>`, and log event IDs derived from canonical JSON
hashes). Seed values enter as candidate or verified claims according to
existing `spec_verified` and source metadata; imported history retains original
timestamps.

- [ ] **Step 4: Add CLI commands and shadow comparison**

Add Typer commands:

```python
@app.command("intelligence-migrate")
def intelligence_migrate(root: Path = typer.Option(Path("."))) -> None:
    database, repository = build_intelligence_repository(root)
    database.create_schema()
    report = import_legacy_state(root, repository)
    console.print_json(data=asdict(report))


@app.command("intelligence-shadow")
def intelligence_shadow(
    root: Path = typer.Option(Path(".")),
    check: bool = typer.Option(False),
) -> None:
    report = compare_legacy_projection(root, build_intelligence_services(root))
    console.print_json(data=asdict(report))
    if check and not report.is_equivalent:
        raise typer.Exit(1)
```

`ShadowReport` must compare model/project/platform counts, effective history
event counts, current rings, and public facts. Differences contain entity,
field, legacy value, canonical value, and accepted-reason fields.

- [ ] **Step 5: Verify migration and shadow behavior**

Run:

```bash
uv run pytest tests/intelligence/test_migration.py tests/intelligence/test_shadow.py -q
uv run radar intelligence-migrate --root .
uv run radar intelligence-shadow --root .
```

Expected: tests pass; commands print JSON reports without modifying YAML or JSONL.

- [ ] **Step 6: Commit migration support**

```bash
git add src/radar/intelligence/migration.py src/radar/intelligence/shadow.py src/radar/cli.py tests/intelligence
git commit -m "feat(intelligence): import and shadow legacy state"
```

---

### Task 4: Job ledger, leases, and scheduler

**Files:**
- Create: `src/radar/intelligence/jobs.py`
- Create: `src/radar/intelligence/scheduler.py`
- Modify: `src/radar/cli.py`
- Test: `tests/intelligence/test_jobs.py`
- Test: `tests/intelligence/test_scheduler.py`

**Interfaces:**
- Produces: `JobKind`, `JobStatus`, `JobResult`, `JobService.acquire()`, `JobService.complete()`, `JobService.fail()`, `build_scheduler()`.
- Consumes: Task 2 repository job methods.

- [ ] **Step 1: Write failing concurrency and idempotency tests**

```python
def test_only_one_worker_acquires_same_job(repository, now) -> None:
    service = JobService(repository, lease_seconds=300)
    first = service.acquire(JobKind.DISCOVERY, "discovery:2026-07-30T10", now)
    second = service.acquire(JobKind.DISCOVERY, "discovery:2026-07-30T10", now)
    assert first is not None
    assert second is None


def test_expired_lease_can_be_reacquired(repository, now) -> None:
    service = JobService(repository, lease_seconds=60)
    first = service.acquire(JobKind.DISCOVERY, "slot", now)
    assert first is not None
    reacquired = service.acquire(JobKind.DISCOVERY, "slot", now + timedelta(seconds=61))
    assert reacquired is not None
    assert reacquired.attempt == 2
```

- [ ] **Step 2: Run job tests and verify they fail**

Run: `uv run pytest tests/intelligence/test_jobs.py tests/intelligence/test_scheduler.py -q`  
Expected: FAIL because job modules do not exist.

- [ ] **Step 3: Implement database-backed job orchestration**

```python
class JobKind(StrEnum):
    DISCOVERY = "discovery"
    ENRICHMENT = "enrichment"
    VERIFICATION = "verification"
    QUALIFICATION = "qualification"
    EXPORT = "export"


@dataclass(frozen=True)
class JobResult:
    job_id: str
    discovered: int = 0
    created: int = 0
    updated: int = 0
    rejected: int = 0
    conflicted: int = 0
    warnings: tuple[str, ...] = ()


class JobService:
    def __init__(self, repository, lease_seconds: int = 900):
        self.repository = repository
        self.lease_seconds = lease_seconds

    def acquire(self, kind: JobKind, idempotency_key: str, now: datetime):
        return self.repository.acquire_job(
            kind=kind.value,
            idempotency_key=idempotency_key,
            leased_until=now + timedelta(seconds=self.lease_seconds),
            now=now,
        )

    def complete(self, job_id: str, result: JobResult, now: datetime) -> None:
        self.repository.complete_job(job_id, asdict(result), now)

    def fail(self, job_id: str, error: str, now: datetime) -> None:
        self.repository.fail_job(job_id, error, now)
```

Repository acquisition must be a single transaction using a unique
`idempotency_key`; PostgreSQL uses row locking and SQLite uses an immediate
write transaction.

- [ ] **Step 4: Add the built-in schedule and CLI entry point**

```python
def build_scheduler(run_job: Callable[[JobKind], None]) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_job, "interval", hours=2, args=[JobKind.DISCOVERY],
        id="discovery", max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        run_job, "cron", hour=3, minute=0, args=[JobKind.ENRICHMENT],
        id="enrichment", max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        run_job, "cron", day_of_week="sun", hour=4, minute=0,
        args=[JobKind.VERIFICATION], id="verification", max_instances=1, coalesce=True,
    )
    return scheduler
```

Add `radar intelligence-scheduler --root .` and
`radar intelligence-run <discovery|enrichment|verification|qualification|export>`.

- [ ] **Step 5: Verify scheduler and job behavior**

Run:

```bash
uv run pytest tests/intelligence/test_jobs.py tests/intelligence/test_scheduler.py -q
uv run ruff check src/radar/intelligence/jobs.py src/radar/intelligence/scheduler.py
```

Expected: all checks pass; scheduler tests assert the two-hour, daily, and weekly triggers.

- [ ] **Step 6: Commit job orchestration**

```bash
git add src/radar/intelligence/jobs.py src/radar/intelligence/scheduler.py src/radar/cli.py tests/intelligence
git commit -m "feat(intelligence): add durable scheduled jobs"
```

---

### Task 5: Source adapter protocol and evidence snapshots

**Files:**
- Create: `src/radar/intelligence/sources/__init__.py`
- Create: `src/radar/intelligence/sources/base.py`
- Create: `src/radar/intelligence/sources/registry.py`
- Create: `src/radar/intelligence/snapshots.py`
- Test: `tests/intelligence/sources/test_base.py`
- Test: `tests/intelligence/test_snapshots.py`

**Interfaces:**
- Produces: `SourceAdapter`, `SourceRecord`, `DiscoveryCandidate`, `SnapshotStore`, `build_source_adapters(config, client)`.
- Consumes: Task 1 evidence enums and Task 4 jobs.

- [ ] **Step 1: Write failing normalization and checksum tests**

```python
def test_source_record_checksum_is_content_addressed() -> None:
    first = SourceRecord.from_bytes(
        source_id="hf", url="https://example.com/model", body=b'{"id":"x"}',
        retrieved_at=NOW, strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    second = SourceRecord.from_bytes(
        source_id="hf", url="https://example.com/model", body=b'{"id":"x"}',
        retrieved_at=NOW, strength=EvidenceStrength.TRUSTED_REGISTRY,
    )
    assert first.checksum == second.checksum == (
        "sha256:5e2b92cc57ce618dfbb54844a31775e4"
        "b95c6fb552ee6bf5a068133c12d2ad90"
    )


def test_snapshot_store_does_not_duplicate_same_content(tmp_path) -> None:
    store = SnapshotStore(tmp_path)
    one = store.write("hf", "sha256:abc", b"payload")
    two = store.write("hf", "sha256:abc", b"payload")
    assert one == two
    assert len(list(tmp_path.rglob("*.*"))) == 1
```

- [ ] **Step 2: Run adapter tests and verify they fail**

Run: `uv run pytest tests/intelligence/sources/test_base.py tests/intelligence/test_snapshots.py -q`  
Expected: FAIL because source contracts do not exist.

- [ ] **Step 3: Implement normalized source contracts**

```python
class SourceRecord(FrozenModel):
    source_id: str
    url: str
    body: bytes
    retrieved_at: datetime
    strength: EvidenceStrength
    checksum: str
    content_type: str | None = None

    @classmethod
    def from_bytes(cls, *, source_id: str, url: str, body: bytes,
                   retrieved_at: datetime, strength: EvidenceStrength,
                   content_type: str | None = None) -> SourceRecord:
        digest = hashlib.sha256(body).hexdigest()
        return cls(
            source_id=source_id, url=url, body=body, retrieved_at=retrieved_at,
            strength=strength, checksum=f"sha256:{digest}", content_type=content_type,
        )


class DiscoveryCandidate(FrozenModel):
    source_record: SourceRecord
    external_id: str
    publisher_hint: str
    release_name: str
    category_hint: ModelCategory | None = None
    artifact_urls: list[str] = Field(default_factory=list)


class SourceAdapter(Protocol):
    id: str
    async def discover(self, since: datetime) -> list[DiscoveryCandidate]: ...
    async def fetch(self, url: str) -> SourceRecord: ...
```

Snapshot paths are
`data/intelligence/snapshots/<source-id>/<first-two-hash-chars>/<hash>.<extension>`.
Atomic writes use a temporary file beside the final target followed by
`Path.replace`.

- [ ] **Step 4: Implement configured registry**

`build_source_adapters` returns enabled adapters in stable source-ID order and
accepts the existing shared `httpx.AsyncClient`. Unknown source types raise a
configuration error during startup instead of disappearing silently.

- [ ] **Step 5: Verify adapter foundation**

Run:

```bash
uv run pytest tests/intelligence/sources/test_base.py tests/intelligence/test_snapshots.py -q
uv run ruff check src/radar/intelligence/sources src/radar/intelligence/snapshots.py
uv run mypy src/radar/intelligence/sources src/radar/intelligence/snapshots.py
```

Expected: all checks pass.

- [ ] **Step 6: Commit source foundation**

```bash
git add src/radar/intelligence/sources src/radar/intelligence/snapshots.py tests/intelligence
git commit -m "feat(intelligence): add provenance source adapters"
```

---

### Task 6: Comprehensive Hugging Face release discovery

**Files:**
- Create: `src/radar/intelligence/sources/huggingface.py`
- Create: `config/intelligence-sources.yaml`
- Modify: `src/radar/intelligence/sources/registry.py`
- Test: `tests/intelligence/sources/test_huggingface.py`
- Test fixture: `tests/fixtures/intelligence/hf_kimi_k3.json`
- Test fixture: `tests/fixtures/intelligence/hf_embedding.json`
- Test fixture: `tests/fixtures/intelligence/hf_speech.json`

**Interfaces:**
- Consumes: Task 5 adapter contracts; existing `parse_architecture`.
- Produces: `HuggingFaceAdapter`, `HF_PIPELINE_CATEGORIES`, structured candidate claims and artifact URLs.

- [ ] **Step 1: Write the failing Kimi-style and six-category tests**

```python
@pytest.mark.asyncio
async def test_discovers_new_official_multimodal_release(fake_hf_client) -> None:
    adapter = HuggingFaceAdapter(
        client=fake_hf_client,
        publishers={"moonshotai": "publisher:moonshot-ai"},
    )
    candidates = await adapter.discover(datetime(2026, 7, 30, tzinfo=UTC))
    kimi = next(c for c in candidates if c.external_id == "moonshotai/Kimi-K3")
    assert kimi.category_hint == ModelCategory.MULTIMODAL
    assert kimi.source_record.strength == EvidenceStrength.TRUSTED_REGISTRY
    assert "https://huggingface.co/moonshotai/Kimi-K3" in kimi.artifact_urls


def test_every_supported_pipeline_maps_to_category() -> None:
    expected = {
        "text-generation": ModelCategory.TEXT_REASONING,
        "image-text-to-text": ModelCategory.MULTIMODAL,
        "feature-extraction": ModelCategory.EMBEDDING_RERANKING,
        "automatic-speech-recognition": ModelCategory.SPEECH_AUDIO,
        "text-to-speech": ModelCategory.SPEECH_AUDIO,
        "text-to-image": ModelCategory.IMAGE_VIDEO,
        "text-to-video": ModelCategory.IMAGE_VIDEO,
        "image-to-text": ModelCategory.VISION_DOCUMENT,
        "document-question-answering": ModelCategory.VISION_DOCUMENT,
    }
    assert HF_PIPELINE_CATEGORIES == expected
```

- [ ] **Step 2: Run HF adapter tests and verify they fail**

Run: `uv run pytest tests/intelligence/sources/test_huggingface.py -q`  
Expected: FAIL because `HuggingFaceAdapter` does not exist.

- [ ] **Step 3: Implement multi-pipeline discovery**

```python
HF_PIPELINE_CATEGORIES = {
    "text-generation": ModelCategory.TEXT_REASONING,
    "image-text-to-text": ModelCategory.MULTIMODAL,
    "feature-extraction": ModelCategory.EMBEDDING_RERANKING,
    "automatic-speech-recognition": ModelCategory.SPEECH_AUDIO,
    "text-to-speech": ModelCategory.SPEECH_AUDIO,
    "text-to-image": ModelCategory.IMAGE_VIDEO,
    "text-to-video": ModelCategory.IMAGE_VIDEO,
    "image-to-text": ModelCategory.VISION_DOCUMENT,
    "document-question-answering": ModelCategory.VISION_DOCUMENT,
}


class HuggingFaceAdapter:
    id = "huggingface"

    def __init__(self, client, publishers: dict[str, str], per_category_limit: int = 100):
        self.client = client
        self.publishers = publishers
        self.per_category_limit = per_category_limit

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]:
        candidates: dict[str, DiscoveryCandidate] = {}
        for pipeline_tag, category in HF_PIPELINE_CATEGORIES.items():
            response = await self.client.get(
                "https://huggingface.co/api/models",
                params={
                    "pipeline_tag": pipeline_tag,
                    "sort": "lastModified",
                    "direction": -1,
                    "limit": self.per_category_limit,
                    "full": True,
                },
            )
            response.raise_for_status()
            body = response.content
            record = SourceRecord.from_bytes(
                source_id=self.id,
                url=str(response.request.url),
                body=body,
                retrieved_at=datetime.now(UTC),
                strength=EvidenceStrength.TRUSTED_REGISTRY,
                content_type="application/json",
            )
            for item in response.json():
                modified = parse_datetime(item.get("lastModified"))
                if modified is None or modified < since:
                    continue
                repo = item["id"]
                owner = repo.split("/", 1)[0].lower()
                candidates[repo.lower()] = DiscoveryCandidate(
                    source_record=record,
                    external_id=repo,
                    publisher_hint=self.publishers.get(owner, f"provisional:{owner}"),
                    release_name=repo.split("/", 1)[-1],
                    category_hint=category,
                    artifact_urls=[f"https://huggingface.co/{repo}"],
                )
        return [candidates[key] for key in sorted(candidates)]
```

The enrichment fetch must retrieve API metadata, `config.json`, model card,
siblings, safetensors metadata, gating, license, and quantization configuration
as separate evidence observations. It reuses `parse_architecture` but emits
canonical candidate claims instead of `HFModelData`.

- [ ] **Step 4: Configure official publisher scopes**

`config/intelligence-sources.yaml` contains enabled adapters, official
publisher handles/domains, per-category limits, request concurrency, and rate
limits. Seed at least the publishers already represented in
`config/model-seed.yaml`; unknown publishers remain provisional until another
official signal resolves them.

- [ ] **Step 5: Verify HF coverage and no regression**

Run:

```bash
uv run pytest tests/intelligence/sources/test_huggingface.py tests/test_models_radar_hf.py -q
uv run ruff check src/radar/intelligence/sources/huggingface.py
```

Expected: new and legacy HF tests pass.

- [ ] **Step 6: Commit Hugging Face discovery**

```bash
git add config/intelligence-sources.yaml src/radar/intelligence/sources tests/intelligence/sources tests/fixtures/intelligence
git commit -m "feat(intelligence): discover releases across Hugging Face categories"
```

---

### Task 7: Remaining official channels and evidence sources

**Files:**
- Create: `src/radar/intelligence/sources/github.py`
- Create: `src/radar/intelligence/sources/feeds.py`
- Create: `src/radar/intelligence/sources/announcements.py`
- Create: `src/radar/intelligence/sources/registries.py`
- Create: `src/radar/intelligence/sources/evidence.py`
- Modify: `src/radar/intelligence/sources/registry.py`
- Modify: `config/intelligence-sources.yaml`
- Test: `tests/intelligence/sources/test_github.py`
- Test: `tests/intelligence/sources/test_feeds.py`
- Test: `tests/intelligence/sources/test_announcements.py`
- Test: `tests/intelligence/sources/test_registries.py`
- Test: `tests/intelligence/sources/test_evidence.py`

**Interfaces:**
- Consumes: Task 5 `SourceAdapter` and configured official publisher domains.
- Produces: discovery candidates from GitHub organization activity, releases/tags, RSS/Atom, stable announcement pages, ModelScope, Ollama, package/container registries, benchmark maintainers, papers, security, and license evidence.

- [ ] **Step 1: Write failing official-source classification tests**

```python
@pytest.mark.asyncio
async def test_github_official_org_release_is_public_discovery(fake_github_client) -> None:
    adapter = GitHubReleaseAdapter(
        fake_github_client,
        organizations={"MoonshotAI": "publisher:moonshot-ai"},
    )
    candidates = await adapter.discover(datetime(2026, 7, 29, tzinfo=UTC))
    kimi = next(c for c in candidates if c.external_id == "MoonshotAI/Kimi-K3")
    assert kimi.source_record.strength == EvidenceStrength.OFFICIAL_REPOSITORY


@pytest.mark.asyncio
async def test_feed_entry_outside_official_domain_stays_internal(fake_feed_client) -> None:
    adapter = OfficialFeedAdapter(
        fake_feed_client,
        feeds=[FeedConfig(
            id="moonshot",
            url="https://news.example.net/moonshot.xml",
            publisher_id="publisher:moonshot-ai",
            official_domains=["moonshot.ai"],
        )],
    )
    candidate = (await adapter.discover(datetime(2026, 7, 29, tzinfo=UTC)))[0]
    assert candidate.source_record.strength == EvidenceStrength.AGGREGATOR
```

- [ ] **Step 2: Run discovery tests and verify they fail**

Run:

```bash
uv run pytest tests/intelligence/sources/test_github.py \
  tests/intelligence/sources/test_feeds.py \
  tests/intelligence/sources/test_announcements.py \
  tests/intelligence/sources/test_registries.py \
  tests/intelligence/sources/test_evidence.py -q
```

Expected: FAIL because the adapters do not exist.

- [ ] **Step 3: Implement GitHub official-organization discovery**

```python
class GitHubReleaseAdapter:
    id = "github-releases"

    def __init__(self, client, organizations: dict[str, str]):
        self.client = client
        self.organizations = {key.lower(): value for key, value in organizations.items()}

    async def discover(self, since: datetime) -> list[DiscoveryCandidate]:
        candidates: list[DiscoveryCandidate] = []
        for organization in sorted(self.organizations):
            response = await self.client.get(
                f"https://api.github.com/orgs/{organization}/repos",
                params={"sort": "pushed", "direction": "desc", "per_page": 100},
            )
            response.raise_for_status()
            record = SourceRecord.from_bytes(
                source_id=self.id,
                url=str(response.request.url),
                body=response.content,
                retrieved_at=datetime.now(UTC),
                strength=EvidenceStrength.OFFICIAL_REPOSITORY,
                content_type="application/json",
            )
            for repo in response.json():
                pushed_at = parse_datetime(repo.get("pushed_at"))
                if pushed_at is None or pushed_at < since:
                    continue
                candidates.append(DiscoveryCandidate(
                    source_record=record,
                    external_id=repo["full_name"],
                    publisher_hint=self.organizations[organization],
                    release_name=repo["name"],
                    artifact_urls=[repo["html_url"]],
                ))
        return sorted(candidates, key=lambda item: item.external_id.lower())
```

For each changed repository, fetch releases/tags and configured release-manifest
paths. Reuse existing GitHub authentication/rate-limit headers and record
remaining quota in source health.

- [ ] **Step 4: Implement RSS/Atom and announcement adapters**

Use `feedparser` for feed parsing. Canonicalize entry URLs, prefer entry IDs,
and hash title/link/published/source into stable external IDs. Official-domain
entries receive `OFFICIAL_ANNOUNCEMENT`; off-domain syndication receives
`AGGREGATOR`.

The announcement adapter stores `ETag` and `Last-Modified`, performs
conditional GETs, and emits candidates only when the body checksum changes.
Configured CSS selectors or JSON paths extract release links; selector
failures are recorded as source-health warnings.

- [ ] **Step 5: Expand source configuration**

Add official feeds, organization scopes, documentation release pages, and
registry endpoints for publishers already in the catalog. Every entry includes
`publisher_id`, `source_class`, `enabled`, and expected official domains.

Implement configured registry and evidence adapters with an explicit schema:

```python
class JsonRegistryConfig(BaseModel):
    id: str
    url: str
    publisher_id: str | None = None
    strength: EvidenceStrength
    items_path: list[str]
    id_field: str
    name_field: str
    updated_field: str
    artifact_url_field: str
    category: ModelCategory | None = None


class EvidenceSourceConfig(BaseModel):
    id: str
    kind: Literal["benchmark", "paper", "security", "license"]
    url: str
    strength: EvidenceStrength
    subject_id_field: str
    observed_at_field: str
```

Seed ModelScope and Ollama registry endpoints plus the package/container,
benchmark, paper, OSV, and license sources already used by the repository.
Registry items produce discovery candidates; evidence items produce candidate
claims linked by exact canonical subject aliases. Unresolved subjects enter the
review queue and never attach by fuzzy match.

- [ ] **Step 6: Verify adapters and legacy collectors**

Run:

```bash
uv run pytest tests/intelligence/sources tests/test_collectors_github.py \
  tests/test_collectors_rss.py -q
uv run ruff check src/radar/intelligence/sources
```

Expected: all tests pass; legacy collector behavior is unchanged.

- [ ] **Step 7: Commit official-source discovery**

```bash
git add config/intelligence-sources.yaml src/radar/intelligence/sources tests/intelligence/sources
git commit -m "feat(intelligence): ingest official release channels"
```

---

### Task 8: Identity resolution and cross-source deduplication

**Files:**
- Create: `src/radar/intelligence/identity.py`
- Create: `src/radar/intelligence/dedupe.py`
- Test: `tests/intelligence/test_identity.py`
- Test: `tests/intelligence/test_dedupe.py`

**Interfaces:**
- Consumes: Tasks 5–7 `DiscoveryCandidate`, publishers, families, releases, and repository aliases.
- Produces: `IdentityResolution`, `IdentityResolver.resolve()`, `CandidateCluster`, `cluster_candidates()`.

- [ ] **Step 1: Write failing Kimi cross-source identity tests**

```python
def test_hf_github_and_blog_resolve_to_one_release(repository) -> None:
    resolver = IdentityResolver(repository)
    candidates = [
        candidate("moonshotai/Kimi-K3", "moonshotai", "Kimi-K3"),
        candidate("MoonshotAI/Kimi-K3", "MoonshotAI", "Kimi K3"),
        candidate("https://moonshot.ai/blog/kimi-k3", "moonshot.ai", "Kimi K3 released"),
    ]

    clusters = cluster_candidates(candidates, resolver)

    assert len(clusters) == 1
    assert clusters[0].canonical_release_id == "release:moonshot-ai:kimi:k3"
    assert len(clusters[0].candidates) == 3


def test_ambiguous_family_opens_review_instead_of_merging(repository) -> None:
    resolver = IdentityResolver(repository)
    result = resolver.resolve(candidate("acme/K3", "unknown", "K3"))
    assert result.release_id is None
    assert result.review_code == "ambiguous_identity"
```

- [ ] **Step 2: Run identity tests and verify they fail**

Run: `uv run pytest tests/intelligence/test_identity.py tests/intelligence/test_dedupe.py -q`  
Expected: FAIL because identity modules do not exist.

- [ ] **Step 3: Implement normalization and exact alias resolution**

```python
_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def normalize_identity(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "-".join(part for part in _TOKEN_RE.split(normalized) if part)


@dataclass(frozen=True)
class IdentityResolution:
    publisher_id: str | None
    family_id: str | None
    release_id: str | None
    confidence: float
    matched_aliases: tuple[str, ...]
    review_code: str | None = None


class IdentityResolver:
    def __init__(self, repository):
        self.repository = repository

    def resolve(self, candidate: DiscoveryCandidate) -> IdentityResolution:
        publisher = self.repository.resolve_publisher_alias(candidate.publisher_hint)
        if publisher is None:
            return IdentityResolution(None, None, None, 0.0, (), "unknown_publisher")
        release = self.repository.resolve_release_alias(
            publisher.id, normalize_identity(candidate.release_name)
        )
        if release:
            return IdentityResolution(
                publisher.id, release.family_id, release.id, 1.0,
                (candidate.external_id, candidate.release_name),
            )
        return self._resolve_new_release(publisher, candidate)
```

New-release resolution requires a unique publisher plus a normalized release
name with at least one official/trusted candidate. Fuzzy matches may suggest a
review but may not auto-merge. Repository aliases are append-only.

- [ ] **Step 4: Implement deterministic clustering**

Cluster by resolved release ID first, then by exact normalized publisher/name.
Conflicting category or lane hints stay in one cluster but produce candidate
conflict claims. Stable cluster IDs hash sorted candidate source IDs and
external IDs.

- [ ] **Step 5: Verify identity and dedupe**

Run:

```bash
uv run pytest tests/intelligence/test_identity.py tests/intelligence/test_dedupe.py -q
uv run ruff check src/radar/intelligence/identity.py src/radar/intelligence/dedupe.py
uv run mypy src/radar/intelligence/identity.py src/radar/intelligence/dedupe.py
```

Expected: all checks pass.

- [ ] **Step 6: Commit identity resolution**

```bash
git add src/radar/intelligence/identity.py src/radar/intelligence/dedupe.py tests/intelligence
git commit -m "feat(intelligence): resolve and deduplicate releases"
```

---

### Task 9: Lifecycle, automated verification, and review exceptions

**Files:**
- Create: `src/radar/intelligence/lifecycle.py`
- Create: `src/radar/intelligence/verification.py`
- Create: `src/radar/intelligence/review.py`
- Create: `src/radar/intelligence/freshness.py`
- Create: `src/radar/intelligence/source_health.py`
- Test: `tests/intelligence/test_lifecycle.py`
- Test: `tests/intelligence/test_verification.py`
- Test: `tests/intelligence/test_review.py`
- Test: `tests/intelligence/test_freshness.py`
- Test: `tests/intelligence/test_intelligence_source_health.py`

**Interfaces:**
- Consumes: canonical claims/evidence and Task 2 repository.
- Produces: `LifecycleService.transition()`, `VerificationService.verify_release()`, `VerificationResult`, `ReviewService`, `FreshnessService`, `SourceHealthService`.

- [ ] **Step 1: Write failing transition and conflict tests**

```python
def test_cannot_skip_verified_and_qualified(repository, detected_release) -> None:
    service = LifecycleService(repository)
    with pytest.raises(InvalidLifecycleTransition, match="detected -> recommended"):
        service.transition(
            detected_release.id,
            LifecycleState.RECOMMENDED,
            reason="skip",
            evidence_ids=["evidence:one"],
            now=NOW,
        )


def test_official_conflict_opens_review_and_blocks_verification(repository) -> None:
    seed_conflicting_license_claims(repository)
    result = VerificationService(repository).verify_release("release:kimi-k3", NOW)
    assert result.verified is False
    assert result.review_exception.code == "conflicting_authoritative_claims"
    assert repository.get_release("release:kimi-k3").lifecycle == LifecycleState.DETECTED
```

- [ ] **Step 2: Run lifecycle tests and verify they fail**

Run:

```bash
uv run pytest tests/intelligence/test_lifecycle.py \
  tests/intelligence/test_verification.py tests/intelligence/test_review.py \
  tests/intelligence/test_freshness.py \
  tests/intelligence/test_intelligence_source_health.py -q
```

Expected: FAIL because lifecycle services do not exist.

- [ ] **Step 3: Implement the state machine**

```python
ALLOWED_TRANSITIONS = {
    LifecycleState.DETECTED: {LifecycleState.VERIFIED},
    LifecycleState.VERIFIED: {LifecycleState.QUALIFIED},
    LifecycleState.QUALIFIED: {LifecycleState.RECOMMENDED},
    LifecycleState.RECOMMENDED: set(),
}


class LifecycleService:
    def __init__(self, repository):
        self.repository = repository

    def transition(self, release_id: str, target: LifecycleState, *,
                   reason: str, evidence_ids: list[str], now: datetime) -> None:
        release = self.repository.get_release_required(release_id)
        if target not in ALLOWED_TRANSITIONS[release.lifecycle]:
            raise InvalidLifecycleTransition(
                f"{release.lifecycle.value} -> {target.value} is not allowed"
            )
        if not evidence_ids:
            raise InvalidLifecycleTransition("Lifecycle transitions require evidence")
        self.repository.append_lifecycle_transition(
            LifecycleTransition(
                release_id=release_id,
                from_state=release.lifecycle,
                to_state=target,
                observed_at=now,
                reason=reason,
                evidence_ids=evidence_ids,
            )
        )
        self.repository.set_release_lifecycle(release_id, target)
```

Corrections never reverse the event log. A later correction event invalidates
the affected qualification/recommendation projection and reopens review.

- [ ] **Step 4: Implement automated verification**

Required predicates are configured by lane and model category. Verification
selects the strongest non-conflicting current claim for each predicate,
requires official ownership and artifacts, records the input evidence IDs, and
returns:

```python
@dataclass(frozen=True)
class VerificationResult:
    release_id: str
    verified: bool
    verified_claim_ids: tuple[str, ...]
    missing_predicates: tuple[str, ...]
    review_exception: ReviewException | None
```

Conflicts between equal/high-authority claims open
`conflicting_authoritative_claims`. Missing requirements keep the release
Detected without opening a review unless the official source explicitly claims
the missing artifact exists.

- [ ] **Step 5: Implement review resolution**

`ReviewService.resolve(exception_id, resolution, evidence_ids, now)` accepts
`accept_claim`, `reject_claim`, `merge_identity`, or `dismiss_candidate`.
Resolution appends correction evidence and a lifecycle event where applicable;
it never edits raw evidence.

- [ ] **Step 6: Implement freshness and source circuit breakers**

```python
FRESHNESS_WINDOWS = {
    "release_identity_new": timedelta(days=7),
    "release_identity_established": timedelta(days=30),
    "artifact_availability": timedelta(days=7),
    "license": timedelta(days=30),
    "platform_compatibility": timedelta(days=30),
    "benchmark": timedelta(days=90),
    "hardware_spec": timedelta(days=90),
    "security_advisory": timedelta(days=1),
    "package_release": timedelta(days=1),
}


class FreshnessService:
    def status(self, predicate_class: str, retrieved_at: datetime,
               now: datetime) -> ClaimFreshness:
        window = FRESHNESS_WINDOWS[predicate_class]
        return (
            ClaimFreshness.FRESH
            if now - retrieved_at <= window
            else ClaimFreshness.STALE
        )


class SourceHealthService:
    def record_failure(self, source_id: str, error: str, now: datetime) -> None:
        state = self.repository.increment_source_failure(source_id, error, now)
        if state.consecutive_failures >= 5:
            self.repository.open_source_circuit(
                source_id, until=now + timedelta(hours=2)
            )
```

Success resets consecutive failures and records latency/items. An open circuit
skips network work, preserves prior projections, and records an explicit
skipped job result. Stale claims cannot satisfy fresh qualification gates but
remain visible.

- [ ] **Step 7: Verify lifecycle behavior**

Run:

```bash
uv run pytest tests/intelligence/test_lifecycle.py \
  tests/intelligence/test_verification.py tests/intelligence/test_review.py \
  tests/intelligence/test_freshness.py \
  tests/intelligence/test_intelligence_source_health.py -q
uv run ruff check src/radar/intelligence/lifecycle.py \
  src/radar/intelligence/verification.py src/radar/intelligence/review.py \
  src/radar/intelligence/freshness.py src/radar/intelligence/source_health.py
```

Expected: all checks pass.

- [ ] **Step 8: Commit trust lifecycle**

```bash
git add src/radar/intelligence/lifecycle.py src/radar/intelligence/verification.py \
  src/radar/intelligence/review.py src/radar/intelligence/freshness.py \
  src/radar/intelligence/source_health.py tests/intelligence
git commit -m "feat(intelligence): enforce release trust lifecycle"
```

---

### Task 10: Category qualification and version-aware platform intelligence

**Files:**
- Create: `src/radar/intelligence/qualification.py`
- Create: `src/radar/intelligence/qualifiers/__init__.py`
- Create: `src/radar/intelligence/qualifiers/language.py`
- Create: `src/radar/intelligence/qualifiers/embedding.py`
- Create: `src/radar/intelligence/qualifiers/audio.py`
- Create: `src/radar/intelligence/qualifiers/media.py`
- Create: `src/radar/intelligence/qualifiers/document.py`
- Create: `src/radar/intelligence/platforms.py`
- Test: `tests/intelligence/test_qualification.py`
- Test: `tests/intelligence/test_platform_intelligence.py`

**Interfaces:**
- Consumes: existing memory/capacity functions, verified claims, and imported platform seed.
- Produces: `QualificationService.qualify()`, `CategoryQualifier`, `PlatformIntelligenceService`, current compatibility projection.

- [ ] **Step 1: Write failing category-dispatch and platform-staleness tests**

```python
@pytest.mark.parametrize(
    ("category", "qualifier_type"),
    [
        (ModelCategory.TEXT_REASONING, LanguageQualifier),
        (ModelCategory.MULTIMODAL, LanguageQualifier),
        (ModelCategory.EMBEDDING_RERANKING, EmbeddingQualifier),
        (ModelCategory.SPEECH_AUDIO, AudioQualifier),
        (ModelCategory.IMAGE_VIDEO, MediaQualifier),
        (ModelCategory.VISION_DOCUMENT, DocumentQualifier),
    ],
)
def test_every_category_has_a_qualifier(category, qualifier_type) -> None:
    assert isinstance(build_qualifier(category), qualifier_type)


def test_removed_platform_doc_marks_claim_stale_not_no(repository) -> None:
    seed_documented_support(repository, support=SupportStatus.YES)
    service = PlatformIntelligenceService(repository)
    service.mark_source_unavailable("evidence:vllm:kimi", NOW)
    assertion = repository.get_compatibility("compat:vllm:kimi")
    assert assertion.support == SupportStatus.YES
    assert repository.get_claim(assertion.id).state == ClaimState.STALE
```

- [ ] **Step 2: Run qualification tests and verify they fail**

Run:

```bash
uv run pytest tests/intelligence/test_qualification.py \
  tests/intelligence/test_platform_intelligence.py -q
```

Expected: FAIL because qualification modules do not exist.

- [ ] **Step 3: Implement the qualification protocol and dispatch**

```python
class CategoryQualifier(Protocol):
    def qualify(self, release: Release, claims: dict[str, Claim],
                compatibility: list[CompatibilityAssertion]) -> Qualification: ...


QUALIFIER_FACTORIES = {
    ModelCategory.TEXT_REASONING: LanguageQualifier,
    ModelCategory.MULTIMODAL: LanguageQualifier,
    ModelCategory.EMBEDDING_RERANKING: EmbeddingQualifier,
    ModelCategory.SPEECH_AUDIO: AudioQualifier,
    ModelCategory.IMAGE_VIDEO: MediaQualifier,
    ModelCategory.VISION_DOCUMENT: DocumentQualifier,
}


def build_qualifier(category: ModelCategory) -> CategoryQualifier:
    return QUALIFIER_FACTORIES[category]()
```

Each qualifier declares `required_predicates`, `fit_metrics`, and
`risk_checks`. The language qualifier adapts existing
`models_radar.memory`, `device_fit`, and `capacity` code rather than
duplicating formulas.

- [ ] **Step 4: Implement version-aware platform assertions**

`PlatformIntelligenceService.upsert_assertion` requires platform version,
feature, support status, evidence level, and evidence IDs. Exact platform
versions outrank ranges; tested evidence outranks documented, which outranks
inferred for display. Inferred assertions cannot alone qualify a release.

Import each current `PlatformSeed` as a documented assertion with version
`legacy-snapshot:<verified-date>`, preserving sources and notes.

- [ ] **Step 5: Add platform drift processing**

When a platform release or documentation checksum changes, enqueue only
assertions linked to that source. Successful verification appends a new claim;
unavailable evidence marks the prior claim stale. A verified explicit removal
may create `no`.

- [ ] **Step 6: Verify qualification and existing capacity behavior**

Run:

```bash
uv run pytest tests/intelligence/test_qualification.py \
  tests/intelligence/test_platform_intelligence.py \
  tests/test_capacity_solver.py tests/test_device_fit.py tests/test_platform_matrix.py -q
uv run ruff check src/radar/intelligence/qualification.py \
  src/radar/intelligence/qualifiers src/radar/intelligence/platforms.py
```

Expected: all checks pass.

- [ ] **Step 7: Commit qualification and platform intelligence**

```bash
git add src/radar/intelligence/qualification.py src/radar/intelligence/qualifiers \
  src/radar/intelligence/platforms.py tests/intelligence
git commit -m "feat(intelligence): qualify models and platform support"
```

---

### Task 11: Workspace contexts and adjusted recommendations

**Files:**
- Create: `src/radar/intelligence/workspaces.py`
- Create: `src/radar/intelligence/recommendations.py`
- Test: `tests/intelligence/test_workspaces.py`
- Test: `tests/intelligence/test_recommendations.py`

**Interfaces:**
- Consumes: existing deterministic scoring, capacity, and Task 10 qualification.
- Produces: `WorkspaceInput`, `WorkspaceService`, `RecommendationService.public()`, `RecommendationService.for_workspace()`.

- [ ] **Step 1: Write failing no-login workspace tests**

```python
def test_multiple_workspaces_change_fit_without_users(repository) -> None:
    service = WorkspaceService(repository)
    laptop = service.create(WorkspaceInput(
        name="Laptop Lab",
        devices=[{"device_id": "rtx-4090-24gb", "count": 1}],
        policies={"allowed_licenses": ["apache-2.0", "mit"]},
    ))
    datacenter = service.create(WorkspaceInput(
        name="H200 Cluster",
        devices=[{"device_id": "hgx-h200-8", "count": 2}],
        policies={"allowed_licenses": ["apache-2.0", "mit", "kimi-k3"]},
    ))

    laptop_result = RecommendationService(repository).for_workspace(
        "release:kimi-k3", laptop.id
    )
    dc_result = RecommendationService(repository).for_workspace(
        "release:kimi-k3", datacenter.id
    )
    assert laptop_result.ring != dc_result.ring
    assert laptop_result.workspace_id == laptop.id
    assert dc_result.workspace_id == datacenter.id
```

- [ ] **Step 2: Run workspace tests and verify they fail**

Run: `uv run pytest tests/intelligence/test_workspaces.py tests/intelligence/test_recommendations.py -q`  
Expected: FAIL because workspace services do not exist.

- [ ] **Step 3: Implement versioned workspace documents**

```python
class WorkspaceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    devices: list[dict[str, Any]] = Field(default_factory=list)
    workloads: list[dict[str, Any]] = Field(default_factory=list)
    policies: dict[str, Any] = Field(default_factory=dict)
    watchlists: list[dict[str, Any]] = Field(default_factory=list)


class WorkspaceService:
    def __init__(self, repository):
        self.repository = repository

    def create(self, value: WorkspaceInput):
        return self.repository.create_workspace(
            workspace_id=f"workspace:{uuid4()}",
            schema_version=1,
            payload=value.model_dump(mode="json"),
        )

    def export_document(self, workspace_id: str) -> dict[str, Any]:
        workspace = self.repository.get_workspace_required(workspace_id)
        return {"schema_version": 1, "workspace": workspace.payload}
```

Import rejects unknown schema versions and validates every device ID against
existing device presets or an explicit custom-device schema.

- [ ] **Step 4: Implement transparent recommendation adjustment**

The public recommendation remains immutable. Workspace adjustment evaluates
license policy, required features, hardware/capacity feasibility, budget/power,
and preferred platforms. The returned recommendation includes public ring,
workspace ring, changed factors, evidence IDs, assumptions, and computation
version.

Market-reference releases return comparison context and no ring.

- [ ] **Step 5: Verify workspace behavior**

Run:

```bash
uv run pytest tests/intelligence/test_workspaces.py tests/intelligence/test_recommendations.py -q
uv run ruff check src/radar/intelligence/workspaces.py \
  src/radar/intelligence/recommendations.py
```

Expected: all checks pass.

- [ ] **Step 6: Commit workspace context**

```bash
git add src/radar/intelligence/workspaces.py \
  src/radar/intelligence/recommendations.py tests/intelligence
git commit -m "feat(intelligence): add workspace-aware recommendations"
```

---

### Task 12: Stable application query services

**Files:**
- Create: `src/radar/intelligence/services/__init__.py`
- Create: `src/radar/intelligence/services/catalog.py`
- Create: `src/radar/intelligence/services/releases.py`
- Create: `src/radar/intelligence/services/deployments.py`
- Create: `src/radar/intelligence/services/operations.py`
- Create: `src/radar/intelligence/services/container.py`
- Test: `tests/intelligence/test_catalog_service.py`
- Test: `tests/intelligence/test_release_service.py`
- Test: `tests/intelligence/test_operations_service.py`

**Interfaces:**
- Consumes: Tasks 2–11 repositories/domain services.
- Produces: transport-independent response contracts consumed by API, MCP, CLI, feeds, and static export.

- [ ] **Step 1: Write failing service projection tests**

```python
def test_release_stream_exposes_status_freshness_and_citations(services) -> None:
    result = services.releases.list_changes(since=NOW - timedelta(hours=2), limit=20)
    item = next(row for row in result.items if row.release_id == "release:kimi-k3")
    assert item.lifecycle == "detected"
    assert item.freshness == "fresh"
    assert item.citations[0].url.startswith("https://")


def test_catalog_search_is_stable_and_workspace_aware(services) -> None:
    first = services.catalog.search("multimodal", workspace_id="workspace:dc")
    second = services.catalog.search("multimodal", workspace_id="workspace:dc")
    assert first == second
    assert first.items[0].workspace_recommendation is not None
```

- [ ] **Step 2: Run service tests and verify they fail**

Run:

```bash
uv run pytest tests/intelligence/test_catalog_service.py \
  tests/intelligence/test_release_service.py \
  tests/intelligence/test_operations_service.py -q
```

Expected: FAIL because service modules do not exist.

- [ ] **Step 3: Implement typed response contracts and catalog search**

```python
class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None


class CatalogService:
    def __init__(self, repository, recommendations):
        self.repository = repository
        self.recommendations = recommendations

    def search(self, query: str, *, category: ModelCategory | None = None,
               lifecycle: LifecycleState | None = None,
               workspace_id: str | None = None, cursor: str | None = None,
               limit: int = 50) -> Page[CatalogItem]:
        rows, next_cursor = self.repository.search_releases(
            query=query, category=category, lifecycle=lifecycle,
            cursor=cursor, limit=min(max(limit, 1), 100),
        )
        return Page(
            items=[self._project(row, workspace_id) for row in rows],
            next_cursor=next_cursor,
        )
```

Sorting is deterministic: relevance, lifecycle rank, release date descending,
then canonical ID. Cursors encode the last stable sort tuple.

- [ ] **Step 4: Implement release, deployment, and operations services**

Release projections include lifecycle, lane, category, age, citations,
freshness, confidence, and review status. Deployment services wrap existing
capacity and fit APIs with canonical release/platform resolution. Operations
services expose review exceptions, job history, source health, webhook
delivery, and stale-claim counts.

- [ ] **Step 5: Verify transport-independent services**

Run:

```bash
uv run pytest tests/intelligence/test_catalog_service.py \
  tests/intelligence/test_release_service.py \
  tests/intelligence/test_operations_service.py -q
uv run mypy src/radar/intelligence/services
```

Expected: all checks pass.

- [ ] **Step 6: Commit application services**

```bash
git add src/radar/intelligence/services tests/intelligence
git commit -m "feat(intelligence): add shared application queries"
```

---

### Task 13: Versioned FastAPI REST API

**Files:**
- Create: `src/radar/api/__init__.py`
- Create: `src/radar/api/app.py`
- Create: `src/radar/api/dependencies.py`
- Create: `src/radar/api/routes/releases.py`
- Create: `src/radar/api/routes/catalog.py`
- Create: `src/radar/api/routes/deployments.py`
- Create: `src/radar/api/routes/workspaces.py`
- Create: `src/radar/api/routes/operations.py`
- Create: `src/radar/api/routes/integrations.py`
- Modify: `src/radar/web/app.py`
- Test: `tests/api/test_openapi.py`
- Test: `tests/api/test_releases.py`
- Test: `tests/api/test_workspaces.py`

**Interfaces:**
- Consumes: Task 12 service container.
- Produces: `/api/v1` and a stable OpenAPI document at `/api/v1/openapi.json`.

- [ ] **Step 1: Write failing API contract tests**

```python
def test_openapi_has_versioned_release_and_workspace_routes(api_client) -> None:
    schema = api_client.get("/api/v1/openapi.json").json()
    assert "/api/v1/releases" in schema["paths"]
    assert "/api/v1/workspaces" in schema["paths"]
    assert schema["info"]["version"] == "1.0.0"


def test_release_stream_supports_since_and_workspace(api_client) -> None:
    response = api_client.get(
        "/api/v1/releases",
        params={"since": "2026-07-30T08:00:00Z", "workspace_id": "workspace:dc"},
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["citations"]


def test_public_mode_rejects_mutation(public_api_client) -> None:
    response = public_api_client.post("/api/v1/workspaces", json={"name": "Blocked"})
    assert response.status_code == 403
```

- [ ] **Step 2: Run API tests and verify they fail**

Run: `uv run pytest tests/api -q`  
Expected: FAIL because the versioned API does not exist.

- [ ] **Step 3: Implement the API factory and read-only deployment switch**

```python
def create_api_app(root: Path, *, read_only: bool = False) -> FastAPI:
    app = FastAPI(
        title="On-Prem Intelligence API",
        version="1.0.0",
        docs_url="/api/docs",
        openapi_url="/api/v1/openapi.json",
    )
    app.state.services = build_service_container(root)
    app.state.read_only = read_only
    for router in ROUTERS:
        app.include_router(router, prefix="/api/v1")
    return app


def require_writable(request: Request) -> None:
    if request.app.state.read_only:
        raise HTTPException(status_code=403, detail="This deployment is read-only")
```

No session/user dependency is introduced. Optional deployment API-token
validation is middleware configured by environment and protects all remote
mutations equally.

- [ ] **Step 4: Implement resource routers**

Each endpoint delegates once to a Task 12 service, uses Pydantic response
models, caps `limit` at 100, and translates domain not-found/conflict errors to
404/409. Workspaces accept versioned documents and mutations require
`require_writable`.

- [ ] **Step 5: Compose the API without removing Jinja routes**

Refactor `src/radar/web/app.py:create_app` to start with
`create_api_app(root)` and register the existing Jinja routes on that same
FastAPI instance. API routes already include `/api/v1`; do not mount the API
under another `/api` prefix. Do not redirect `/` until Task 20 cutover.

- [ ] **Step 6: Verify API and legacy web**

Run:

```bash
uv run pytest tests/api tests/test_web.py tests/test_static_site.py -q
uv run ruff check src/radar/api
uv run mypy src/radar/api
```

Expected: all checks pass.

- [ ] **Step 7: Commit the API**

```bash
git add src/radar/api src/radar/web/app.py tests/api
git commit -m "feat(api): expose versioned intelligence services"
```

---

### Task 14: MCP tools over shared services

**Files:**
- Create: `src/radar/mcp_server/intelligence_queries.py`
- Modify: `src/radar/mcp_server/server.py`
- Test: `tests/test_intelligence_queries.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: Task 12 service container.
- Produces MCP tools `search_intelligence`, `list_releases`, `explain_intelligence`, `compare_intelligence`, `find_for_workspace`, `get_source_health`, `list_review_exceptions`.
- Preserves all existing MCP tool names and payloads.

- [ ] **Step 1: Write failing tool-registration and payload tests**

```python
def test_server_registers_intelligence_tools(tmp_path: Path) -> None:
    server = build_mcp_server(tmp_path)
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert {
        "search_intelligence",
        "list_releases",
        "explain_intelligence",
        "find_for_workspace",
        "get_source_health",
    } <= names


def test_list_releases_returns_compact_cited_rows(seeded_server) -> None:
    result = asyncio.run(seeded_server.call_tool(
        "list_releases", {"since": "2026-07-30T08:00:00Z", "limit": 10}
    ))
    payload = result[1].get("result", result[1])
    assert set(payload[0]) <= {
        "id", "name", "category", "lane", "lifecycle", "age", "headline",
        "citation_count", "freshness", "review",
    }
```

- [ ] **Step 2: Run MCP tests and verify they fail**

Run: `uv run pytest tests/test_intelligence_queries.py tests/test_mcp_server.py -q`  
Expected: FAIL because new tools are absent.

- [ ] **Step 3: Implement the transport-independent MCP façade**

```python
class IntelligenceQueryService:
    def __init__(self, services):
        self.services = services

    def list_releases(self, since: str | None, limit: int,
                      workspace_id: str | None = None) -> list[dict[str, Any]]:
        parsed_since = parse_datetime(since) if since else None
        page = self.services.releases.list_changes(
            since=parsed_since, limit=min(max(limit, 1), 100),
            workspace_id=workspace_id,
        )
        return [compact_release(item) for item in page.items]

    def explain(self, entity_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        return self.services.catalog.explain(entity_id, workspace_id=workspace_id)
```

Compact browse tools return citations as counts/headlines. Explain/detail tools
return complete evidence URLs and assumptions.

- [ ] **Step 4: Register MCP tools**

Register thin `@mcp.tool()` wrappers in `server.py`; wrappers perform no
database parsing or scoring. Every workspace-aware tool accepts optional
`workspace_id`.

- [ ] **Step 5: Verify new and existing MCP contracts**

Run:

```bash
uv run pytest tests/test_intelligence_queries.py tests/test_mcp_server.py \
  tests/test_model_queries.py tests/test_capacity_queries.py -q
uv run ruff check src/radar/mcp_server
```

Expected: all existing and new MCP tests pass.

- [ ] **Step 6: Commit MCP modernization**

```bash
git add src/radar/mcp_server tests/test_intelligence_queries.py tests/test_mcp_server.py
git commit -m "feat(mcp): expose unified intelligence services"
```

---

### Task 15: Versioned events, feeds, webhooks, and public snapshot

**Files:**
- Create: `src/radar/intelligence/events.py`
- Create: `src/radar/intelligence/event_log.py`
- Create: `src/radar/reports/intelligence_feeds.py`
- Create: `src/radar/notify/intelligence_webhook.py`
- Create: `src/radar/web/intelligence_snapshot.py`
- Modify: `src/radar/api/routes/integrations.py`
- Test: `tests/intelligence/test_events.py`
- Test: `tests/test_intelligence_feeds.py`
- Test: `tests/test_intelligence_webhook.py`
- Test: `tests/test_intelligence_snapshot.py`

**Interfaces:**
- Consumes: Task 12 service projections and Task 2 repository.
- Produces: `IntelligenceEvent`, append-only JSONL mirror, Atom/RSS/JSON Feed channels, signed webhook payloads, `public-snapshot.v1.json`.

- [ ] **Step 1: Write failing event/feed/signature tests**

```python
def test_event_id_is_stable_for_same_transition() -> None:
    event = IntelligenceEvent.for_lifecycle(
        release_id="release:kimi-k3",
        from_state=LifecycleState.DETECTED,
        to_state=LifecycleState.VERIFIED,
        occurred_at=NOW,
        evidence_ids=["evidence:one"],
    )
    assert event.id == IntelligenceEvent.for_lifecycle(
        release_id="release:kimi-k3",
        from_state=LifecycleState.DETECTED,
        to_state=LifecycleState.VERIFIED,
        occurred_at=NOW,
        evidence_ids=["evidence:one"],
    ).id


def test_rss_atom_and_json_feed_share_item_id(seed_events) -> None:
    atom = render_intelligence_atom(seed_events, "https://radar.example")
    rss = render_intelligence_rss(seed_events, "https://radar.example")
    json_feed = json.loads(render_intelligence_json_feed(seed_events, "https://radar.example"))
    expected = seed_events[0].id
    assert expected in atom
    assert expected in rss
    assert json_feed["items"][0]["id"] == expected


def test_webhook_signature_is_hmac_sha256() -> None:
    body = b'{"event":"release.detected"}'
    assert sign_webhook(body, "secret") == (
        "sha256=e85adc6d6af7bb038d73d8465946be72"
        "c7be8d35865f9ed89ce234795cdb82f4"
    )
```

- [ ] **Step 2: Run delivery tests and verify they fail**

Run:

```bash
uv run pytest tests/intelligence/test_events.py tests/test_intelligence_feeds.py \
  tests/test_intelligence_webhook.py tests/test_intelligence_snapshot.py -q
```

Expected: FAIL because event and intelligence delivery modules do not exist.

- [ ] **Step 3: Implement the versioned event envelope**

```python
class IntelligenceEvent(FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str
    type: str
    occurred_at: datetime
    subject_id: str
    workspace_id: str | None = None
    data: dict[str, Any]
    evidence_ids: list[str]

    @classmethod
    def for_lifecycle(cls, *, release_id: str,
                      from_state: LifecycleState | None,
                      to_state: LifecycleState, occurred_at: datetime,
                      evidence_ids: list[str]) -> IntelligenceEvent:
        data = {
            "from": from_state.value if from_state else None,
            "to": to_state.value,
        }
        canonical = json.dumps(
            [release_id, data, occurred_at.isoformat(), sorted(evidence_ids)],
            separators=(",", ":"), sort_keys=True,
        )
        event_id = f"event:{hashlib.sha256(canonical.encode()).hexdigest()}"
        return cls(
            id=event_id, type=f"release.{to_state.value}",
            occurred_at=occurred_at, subject_id=release_id,
            data=data, evidence_ids=evidence_ids,
        )
```

Append each event transactionally to the database. Mirror public events to
`data/intelligence/events.jsonl` using canonical JSON and idempotent ID checks;
the mirror is rebuild input for ephemeral GitHub Actions.

- [ ] **Step 4: Render feeds and signed webhooks**

Feed item IDs are event IDs. Channel filters accept event type, category,
lifecycle, lane, platform, and workspace watchlist. Public feed generation
rejects workspace IDs. Webhook delivery stores attempt number, HTTP status,
response excerpt, next retry, and terminal state. Retry delays are 1, 5, 30,
120, and 600 minutes.

- [ ] **Step 5: Generate the public snapshot**

```python
class PublicSnapshot(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    releases: list[ReleaseSummary]
    models: list[CatalogItem]
    platforms: list[PlatformSummary]
    hardware: list[HardwareSummary]
    research: list[ResearchSummary]
    events: list[EventSummary]
    source_health: PublicSourceHealth


def build_public_snapshot(services, generated_at: datetime) -> PublicSnapshot:
    return PublicSnapshot(
        generated_at=generated_at,
        releases=services.releases.public_snapshot(),
        models=services.catalog.public_models(),
        platforms=services.catalog.public_platforms(),
        hardware=services.catalog.public_hardware(),
        research=services.catalog.public_research(),
        events=services.releases.public_events(limit=500),
        source_health=services.operations.public_source_health(),
    )
```

The serializer has no workspace field and writes deterministic key/order output
to `_site/data/public-snapshot.v1.json`.

- [ ] **Step 6: Verify feeds, webhooks, and snapshot**

Run:

```bash
uv run pytest tests/intelligence/test_events.py tests/test_intelligence_feeds.py \
  tests/test_intelligence_webhook.py tests/test_intelligence_snapshot.py \
  tests/test_feeds.py tests/test_notify.py -q
uv run ruff check src/radar/intelligence/events.py \
  src/radar/reports/intelligence_feeds.py \
  src/radar/notify/intelligence_webhook.py src/radar/web/intelligence_snapshot.py
```

Expected: all new and legacy delivery tests pass.

- [ ] **Step 7: Commit delivery projections**

```bash
git add src/radar/intelligence/events.py src/radar/intelligence/event_log.py \
  src/radar/reports/intelligence_feeds.py src/radar/notify/intelligence_webhook.py \
  src/radar/web/intelligence_snapshot.py src/radar/api/routes/integrations.py \
  tests/intelligence tests/test_intelligence_*.py
git commit -m "feat(intelligence): publish events feeds and snapshots"
```

---

### Task 16: React/TypeScript application foundation

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/src/app/providers.tsx`
- Create: `frontend/src/app/shell/AppShell.tsx`
- Create: `frontend/src/app/shell/Sidebar.tsx`
- Create: `frontend/src/app/shell/TopBar.tsx`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/design/tokens.css`
- Create: `frontend/src/design/global.css`
- Create: `frontend/src/design/StatusBadge.tsx`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/app/App.test.tsx`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: Task 13 OpenAPI schema.
- Produces: Vite application, generated API types, Architect Workspace shell, shared design primitives.

- [ ] **Step 1: Initialize and lock the frontend toolchain**

Run:

```bash
mkdir -p frontend
cd frontend
npm init -y
npm install react react-dom react-router-dom @tanstack/react-query
npm install -D typescript vite @vitejs/plugin-react vitest jsdom \
  @testing-library/react @testing-library/jest-dom @testing-library/user-event \
  @types/react @types/react-dom eslint typescript-eslint \
  openapi-typescript @playwright/test axe-core
```

Update `frontend/package.json` scripts to:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc -b --pretty false",
    "lint": "eslint .",
    "generate:api": "openapi-typescript ../build/openapi.json -o src/api/generated/schema.d.ts",
    "e2e": "playwright test"
  }
}
```

- [ ] **Step 2: Write the failing shell and route test**

```tsx
// frontend/src/app/App.test.tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";

test("renders the architect workspace navigation", () => {
  render(
    <MemoryRouter initialEntries={["/overview"]}>
      <App />
    </MemoryRouter>,
  );
  expect(screen.getByRole("navigation", { name: "Primary" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(screen.getByText("What changed since your last visit")).toBeVisible();
});
```

- [ ] **Step 3: Run the frontend test and verify it fails**

Run: `cd frontend && npm test -- src/app/App.test.tsx`  
Expected: FAIL because the application files do not exist.

- [ ] **Step 4: Implement build configuration and generated-client wrapper**

```ts
// frontend/vite.config.ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: mode === "static" ? "./" : "/",
  build: { outDir: "../build/frontend", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
}));
```

```ts
// frontend/src/api/client.ts
import type { paths } from "./generated/schema";

export type ApiPaths = paths;

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  workspaceId?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (workspaceId) headers.set("X-Workspace-Id", workspaceId);
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json() as Promise<T>;
}
```

Generate `build/openapi.json` through `uv run python -m radar.api.export_openapi`
then run `npm run generate:api`. Commit generated types and verify regeneration
is clean in CI.

- [ ] **Step 5: Implement the approved shell and Mega tokens**

Use the approved persistent navigation groups: Workspace, Intelligence,
Decide, Monitor, Integrate. Tokens retain Process Blue `#009FDA`, dark hero
`#005F85`, bundled Hanken Grotesk, WCAG AA status colors, 8px spacing scale,
and visible keyboard focus. `StatusBadge` supports Detected, Verified,
Qualified, Recommended, Review, Stale, and Unknown with text plus color.

- [ ] **Step 6: Run frontend verification**

Run:

```bash
cd frontend
npm run generate:api
npm test
npm run typecheck
npm run lint
npm run build
```

Expected: all commands pass and `build/frontend/index.html` exists.

- [ ] **Step 7: Commit frontend foundation**

```bash
git add frontend pyproject.toml
git commit -m "feat(frontend): add architect workspace foundation"
```

---

### Task 17: Balanced Decisions overview and release stream

**Files:**
- Create: `frontend/src/features/overview/OverviewPage.tsx`
- Create: `frontend/src/features/overview/PriorityIntelligence.tsx`
- Create: `frontend/src/features/overview/RecommendedActions.tsx`
- Create: `frontend/src/features/overview/CatalogTrust.tsx`
- Create: `frontend/src/features/releases/ReleaseStreamPage.tsx`
- Create: `frontend/src/features/releases/ReleaseDetailPage.tsx`
- Create: `frontend/src/features/releases/releaseQueries.ts`
- Create: `frontend/src/features/overview/OverviewPage.test.tsx`
- Create: `frontend/src/features/releases/ReleaseStreamPage.test.tsx`

**Interfaces:**
- Consumes: `/api/v1/releases`, `/api/v1/recommendations`, `/api/v1/operations/health`, active workspace.
- Produces: approved default architect briefing and lifecycle stream.

- [ ] **Step 1: Write failing overview behavior tests**

```tsx
test("shows detected releases without presenting them as recommendations", async () => {
  mockApi.release({ lifecycle: "detected", name: "Kimi K3", age: "12m" });
  renderOverview();
  expect(await screen.findByText("Kimi K3")).toBeVisible();
  expect(screen.getByText("Detected")).toBeVisible();
  expect(screen.queryByText("Adopt Kimi K3")).not.toBeInTheDocument();
});

test("shows freshness and review exceptions", async () => {
  mockApi.health({ fresh_claim_pct: 97, stale_claims: 4, review_exceptions: 3 });
  renderOverview();
  expect(await screen.findByText("97%")).toBeVisible();
  expect(screen.getByText("4 stale claims")).toBeVisible();
  expect(screen.getByText("3 review exceptions")).toBeVisible();
});
```

- [ ] **Step 2: Run overview tests and verify they fail**

Run:

```bash
cd frontend
npm test -- src/features/overview/OverviewPage.test.tsx \
  src/features/releases/ReleaseStreamPage.test.tsx
```

Expected: FAIL because overview/release components do not exist.

- [ ] **Step 3: Implement TanStack queries and overview composition**

```tsx
export function OverviewPage() {
  const workspaceId = useActiveWorkspaceId();
  const releases = usePriorityReleases(workspaceId);
  const actions = useRecommendedActions(workspaceId);
  const health = useCatalogHealth();

  return (
    <Page>
      <PageHeader
        title="What changed since your last visit"
        subtitle="Decision briefing · Your estate and policies applied"
        freshness={health.data?.refreshed_at}
      />
      <PriorityIntelligence items={releases.data?.items ?? []} />
      <div className="overview-grid">
        <RecommendedActions items={actions.data?.items ?? []} />
        <OverviewRail health={health.data} />
      </div>
    </Page>
  );
}
```

Each panel implements loading skeleton, empty state, recoverable error with
retry, and stale-data timestamp. Query keys include workspace ID.

- [ ] **Step 4: Implement release stream and detail**

The stream filters by lifecycle, category, lane, age, review, and source.
Cursor pagination uses an explicit “Load more” button. Detail shows the
lifecycle timeline, verified/current claims, conflicting/stale claims,
artifacts, compatibility, qualification, recommendation, and citations.

- [ ] **Step 5: Verify overview accessibility and behavior**

Run:

```bash
cd frontend
npm test -- src/features/overview src/features/releases
npm run typecheck
npm run lint
```

Expected: all checks pass.

- [ ] **Step 6: Commit overview and releases**

```bash
git add frontend/src/features/overview frontend/src/features/releases \
  frontend/src/app/App.tsx
git commit -m "feat(frontend): add balanced decisions release briefing"
```

---

### Task 18: Unified intelligence catalog, search, and detail

**Files:**
- Create: `frontend/src/features/catalog/CatalogPage.tsx`
- Create: `frontend/src/features/catalog/CatalogFilters.tsx`
- Create: `frontend/src/features/catalog/CatalogTable.tsx`
- Create: `frontend/src/features/catalog/ModelDetailPage.tsx`
- Create: `frontend/src/features/catalog/PlatformDetailPage.tsx`
- Create: `frontend/src/features/catalog/HardwarePage.tsx`
- Create: `frontend/src/features/catalog/ResearchPage.tsx`
- Create: `frontend/src/features/catalog/catalogQueries.ts`
- Create: `frontend/src/features/catalog/CatalogPage.test.tsx`
- Create: `frontend/src/features/catalog/ModelDetailPage.test.tsx`

**Interfaces:**
- Consumes: catalog/search/detail/compatibility API endpoints.
- Produces: Models, Platforms, Hardware, and Research navigation with consistent trust/provenance presentation.

- [ ] **Step 1: Write failing catalog tests**

```tsx
test("filters all six model categories", async () => {
  renderCatalog();
  const category = screen.getByLabelText("Model category");
  for (const name of [
    "Text & reasoning", "Multimodal", "Embedding & reranking",
    "Speech & audio", "Image & video", "Vision & documents",
  ]) {
    expect(within(category).getByRole("option", { name })).toBeVisible();
  }
});

test("unknown claim is explicit and cited values link to evidence", async () => {
  mockApi.modelDetail({
    context_tokens: { state: "unknown", reason: "No official value found" },
    license: { state: "verified", value: "kimi-k3", citations: [officialCitation] },
  });
  renderModelDetail();
  expect(await screen.findByText("Unknown")).toBeVisible();
  expect(screen.getByText("No official value found")).toBeVisible();
  expect(screen.getByRole("link", { name: /official source/i })).toHaveAttribute(
    "href", officialCitation.url,
  );
});
```

- [ ] **Step 2: Run catalog tests and verify they fail**

Run:

```bash
cd frontend
npm test -- src/features/catalog/CatalogPage.test.tsx \
  src/features/catalog/ModelDetailPage.test.tsx
```

Expected: FAIL because catalog components do not exist.

- [ ] **Step 3: Implement search and URL-synchronized filters**

Filters are query parameters so views are linkable. Debounced text search uses
300 ms delay and aborts stale requests. Model filters include category, lane,
lifecycle, publisher, license, hardware fit, modality, platform, freshness,
and review status. Tables use semantic markup, sticky headers, column chooser,
and responsive card fallback below 760px.

- [ ] **Step 4: Implement entity detail views**

Model detail uses category-specific sections. Platform detail uses a
version-aware compatibility matrix and evidence-level labels. Hardware and
research retain existing data while switching to canonical service responses.
Every claim renders status, freshness, source link, effective version/range,
and conflict/review state.

- [ ] **Step 5: Verify catalog**

Run:

```bash
cd frontend
npm test -- src/features/catalog
npm run typecheck
npm run lint
```

Expected: all checks pass.

- [ ] **Step 6: Commit catalog**

```bash
git add frontend/src/features/catalog frontend/src/app/App.tsx
git commit -m "feat(frontend): add unified intelligence catalog"
```

---

### Task 19: Compare, deployment planner, workspaces, and operations

**Files:**
- Create: `frontend/src/features/compare/ComparePage.tsx`
- Create: `frontend/src/features/planner/PlannerPage.tsx`
- Create: `frontend/src/features/workspaces/WorkspaceSwitcher.tsx`
- Create: `frontend/src/features/workspaces/WorkspacePage.tsx`
- Create: `frontend/src/features/workspaces/workspaceStore.ts`
- Create: `frontend/src/features/operations/ReviewQueuePage.tsx`
- Create: `frontend/src/features/operations/SourceHealthPage.tsx`
- Create: `frontend/src/features/operations/IntegrationsPage.tsx`
- Create: `frontend/src/features/operations/WatchlistsPage.tsx`
- Create: `frontend/src/features/planner/PlannerPage.test.tsx`
- Create: `frontend/src/features/workspaces/WorkspacePage.test.tsx`
- Create: `frontend/src/features/operations/ReviewQueuePage.test.tsx`

**Interfaces:**
- Consumes: comparison, deployment, workspace, review, source-health, feed, webhook, and MCP/API endpoints.
- Produces: complete Decide, Govern, and Integrate workflows with no login.

- [ ] **Step 1: Write failing workspace and planner tests**

```tsx
test("switching workspace recomputes the plan and recommendation", async () => {
  renderPlanner();
  await userEvent.selectOptions(screen.getByLabelText("Workspace"), "workspace:dc");
  expect(await screen.findByText("16 × H200")).toBeVisible();
  await userEvent.selectOptions(screen.getByLabelText("Workspace"), "workspace:laptop");
  expect(await screen.findByText("Not feasible on current estate")).toBeVisible();
});

test("workspace creation requires no account fields", async () => {
  renderWorkspacePage();
  expect(screen.queryByLabelText(/email|password|user/i)).not.toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Workspace name"), "AI Lab");
  await userEvent.click(screen.getByRole("button", { name: "Save workspace" }));
  expect(await screen.findByText("AI Lab")).toBeVisible();
});
```

- [ ] **Step 2: Run workflow tests and verify they fail**

Run:

```bash
cd frontend
npm test -- src/features/planner src/features/workspaces src/features/operations
```

Expected: FAIL because the workflow components do not exist.

- [ ] **Step 3: Implement workspace switching and persistence**

The active workspace ID is stored in local storage under
`onprem-radar.active-workspace.v1` and validated against the API on load.
Changing it invalidates recommendation, comparison, planner, overview, and
watchlist query keys. Workspace export downloads the versioned JSON document;
import validates before mutation.

- [ ] **Step 4: Implement compare and planner**

Compare supports 2–6 models/platforms/devices, pins differing fields, and
shows public versus workspace verdicts. Planner uses existing capacity input
fields plus workspace estate, includes assumption sheets, and exposes
copy-ready launch recipes only when the selected platform compatibility is
verified or qualified.

- [ ] **Step 5: Implement operations and integrations**

Review queue supports accepted resolution actions from Task 9. Source health
shows last success, failures, latency, items, stale claims, and circuit state.
Integrations shows MCP configuration, REST/OpenAPI links, feed URLs, webhook
delivery, and static export status. Public read-only mode hides mutation
buttons and explains why.

- [ ] **Step 6: Verify workflows**

Run:

```bash
cd frontend
npm test -- src/features/compare src/features/planner \
  src/features/workspaces src/features/operations
npm run typecheck
npm run lint
```

Expected: all checks pass.

- [ ] **Step 7: Commit decision and operations workflows**

```bash
git add frontend/src/features frontend/src/app/App.tsx
git commit -m "feat(frontend): add planning workspaces and operations"
```

---

### Task 20: Static edition, SPA mounting, and legacy route cutover

**Files:**
- Create: `src/radar/api/export_openapi.py`
- Create: `src/radar/web/react_export.py`
- Modify: `src/radar/web/app.py`
- Modify: `src/radar/web/static_site.py`
- Modify: `src/radar/cli.py`
- Modify: `frontend/src/main.tsx`
- Create: `tests/test_react_export.py`
- Modify: `tests/test_web.py`
- Modify: `tests/test_static_site.py`
- Create: `frontend/e2e/public-static.spec.ts`

**Interfaces:**
- Consumes: Task 15 snapshot and Task 16 production build.
- Produces: live SPA at `/`, public static SPA, compatibility redirects, legacy artifact downloads.

- [ ] **Step 1: Write failing live/static cutover tests**

```python
def test_live_root_serves_react_shell_and_api(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    root = client.get("/")
    assert root.status_code == 200
    assert '<div id="root"></div>' in root.text
    assert client.get("/api/v1/releases").status_code == 200


def test_static_export_contains_no_workspace_payload(tmp_path: Path) -> None:
    out = export_react_site(tmp_path, tmp_path / "_site")
    snapshot = json.loads((out / "data" / "public-snapshot.v1.json").read_text())
    assert "workspaces" not in snapshot
    assert (out / "index.html").exists()
    assert (out / "changes.rss").exists()
```

- [ ] **Step 2: Run cutover tests and verify they fail**

Run:

```bash
uv run pytest tests/test_react_export.py tests/test_web.py tests/test_static_site.py -q
```

Expected: FAIL because React export/cutover is not implemented.

- [ ] **Step 3: Implement the live SPA mount**

FastAPI serves `build/frontend` assets with immutable cache headers for hashed
files and no-cache for `index.html`. `/api`, `/mcp`-related docs, `/badge`,
download artifacts, and feeds are registered before the SPA fallback. Legacy
HTML routes redirect to the equivalent React path; existing machine-readable
URLs remain unchanged.

- [ ] **Step 4: Implement static export**

`radar export` runs:

```bash
uv run python -m radar.api.export_openapi --root . --out build/openapi.json
cd frontend && npm run generate:api && npm run build -- --mode static
uv run python -m radar.web.react_export --root . --frontend build/frontend --out _site
```

`react_export` copies hashed assets, writes the public snapshot and feeds,
preserves history/badge/digest downloads, and emits a `404.html` copy of the
shell for GitHub Pages. Static mode uses `HashRouter`; live mode uses
`BrowserRouter`.

- [ ] **Step 5: Verify live and static browser workflows**

Run:

```bash
uv run pytest tests/test_react_export.py tests/test_web.py tests/test_static_site.py -q
cd frontend
npm run build
npx playwright test e2e/public-static.spec.ts
```

Expected: tests pass; Playwright can load overview, models, release detail, and
feeds from the exported directory without a backend.

- [ ] **Step 6: Commit cutover**

```bash
git add src/radar/api/export_openapi.py src/radar/web src/radar/cli.py \
  frontend/src/main.tsx frontend/e2e tests/test_react_export.py \
  tests/test_web.py tests/test_static_site.py
git commit -m "feat(web): cut over to the React intelligence workspace"
```

---

### Task 21: Two-hour public discovery and daily qualification workflows

**Files:**
- Create: `.github/workflows/intelligence-discovery.yml`
- Modify: `.github/workflows/publish.yml`
- Modify: `.github/workflows/ci.yml`
- Modify: `.gitignore`
- Test: `tests/test_intelligence_workflows.py`
- Modify: `README.md`
- Create: `docs/intelligence-operations.md`

**Interfaces:**
- Consumes: intelligence CLI jobs, committed event log, React export.
- Produces: two-hour release detection/publication, daily enrichment, weekly verification, and CI gates.

- [ ] **Step 1: Write failing workflow contract tests**

```python
def test_discovery_workflow_runs_every_two_hours() -> None:
    workflow = load_yaml(".github/workflows/intelligence-discovery.yml")
    assert workflow[True]["schedule"] == [{"cron": "17 */2 * * *"}]
    commands = all_run_commands(workflow)
    assert "radar intelligence-run discovery" in commands
    assert "radar export" in commands


def test_ci_runs_backend_frontend_and_openapi_drift_checks() -> None:
    commands = all_run_commands(load_yaml(".github/workflows/ci.yml"))
    assert "pytest" in commands
    assert "npm test" in commands
    assert "npm run typecheck" in commands
    assert "npm run build" in commands
    assert "git diff --exit-code -- frontend/src/api/generated" in commands
```

- [ ] **Step 2: Run workflow tests and verify they fail**

Run: `uv run pytest tests/test_intelligence_workflows.py -q`  
Expected: FAIL because the discovery workflow is absent.

- [ ] **Step 3: Implement the two-hour discovery workflow**

The workflow:

1. Checks out full history.
2. Installs Python and Node dependencies from locks.
3. Builds the canonical SQLite projection by migrating legacy state and
   replaying `data/intelligence/events.jsonl`.
4. Runs `radar intelligence-run discovery`.
5. Runs lifecycle verification for newly detected records only.
6. Exports the React public site.
7. Runs the scan-health and public-snapshot invariant gates.
8. Commits changed append-only events, source-health records, and snapshot
   manifests with `[skip ci]`.
9. Deploys GitHub Pages only when public output changed.

Use cron `17 */2 * * *`, `workflow_dispatch`, `contents: write`,
`pages: write`, `id-token: write`, and the same Pages concurrency group as the
daily publish workflow.

- [ ] **Step 4: Split daily and weekly jobs cleanly**

Daily publish runs enrichment, qualification, recommendations, full export,
and existing research/trending scans. Weekly verification rechecks every
trusted claim. The existing catalog/source autopilots stop directly mutating
canonical records; they emit discovery candidates through the new jobs.

- [ ] **Step 5: Expand CI and operational documentation**

CI installs frontend dependencies with `npm ci`, starts a PostgreSQL service
container with `TEST_POSTGRES_URL`, runs the repository contract suite against
SQLite and PostgreSQL, verifies generated OpenAPI types are clean, runs
unit/type/lint/build, and runs Playwright on pull requests touching
frontend/API/snapshot code. Document scheduler modes, environment variables,
GitHub token requirements, Postgres URL, optional deployment API token,
backup/restore, source health, and incident recovery.

Add `.superpowers/`, `build/`, and frontend Playwright output to `.gitignore`;
do not ignore committed generated API types or event logs.

- [ ] **Step 6: Verify workflow contracts**

Run:

```bash
uv run pytest tests/test_intelligence_workflows.py tests/test_publish_workflow.py \
  tests/test_source_autopilot_workflow.py -q
uv run ruff check tests/test_intelligence_workflows.py
```

Expected: all workflow tests pass.

- [ ] **Step 7: Commit automation**

```bash
git add .github/workflows .gitignore README.md docs/intelligence-operations.md \
  tests/test_intelligence_workflows.py
git commit -m "ci: publish intelligence updates every two hours"
```

---

### Task 22: End-to-end SLO, migration rehearsal, accessibility, and cutover gate

**Files:**
- Create: `tests/e2e/test_major_release_slo.py`
- Create: `tests/e2e/test_delivery_parity.py`
- Create: `tests/e2e/test_migration_rehearsal.py`
- Create: `frontend/e2e/architect-workspace.spec.ts`
- Create: `frontend/e2e/accessibility.spec.ts`
- Create: `frontend/e2e/visual.spec.ts`
- Create: `scripts/verify_intelligence_release.sh`
- Modify: `CHANGELOG.md`
- Modify: `docs/architecture.md`
- Modify: `docs/persistence.md`

**Interfaces:**
- Consumes: the complete integrated system.
- Produces: one release verification command and auditable cutover evidence.

- [ ] **Step 1: Write the synthetic major-release SLO test**

```python
@pytest.mark.asyncio
async def test_official_release_is_detected_within_two_hours(system, clock) -> None:
    official_time = datetime(2026, 7, 30, 8, 5, tzinfo=UTC)
    system.sources.publish_fixture("moonshotai/Kimi-K3", at=official_time)
    clock.set(datetime(2026, 7, 30, 10, 0, tzinfo=UTC))

    await system.run_discovery()

    release = system.services.catalog.get("release:moonshot-ai:kimi:k3")
    assert release.lifecycle == "detected"
    assert release.first_observed_at - official_time <= timedelta(hours=2)
    assert release.citations[0].strength in {
        "official_artifact", "official_repository", "trusted_registry",
    }
```

- [ ] **Step 2: Write delivery parity and migration rehearsal tests**

Parity seeds one release, platform assertion, public recommendation, workspace
adjustment, and event, then compares API, MCP, RSS/Atom/JSON Feed, static
snapshot, and React fixtures. Migration rehearsal copies repository data to a
temporary root, imports twice, runs shadow comparison, and asserts effective
history/rings/counts are equivalent.

- [ ] **Step 3: Write Playwright architect and accessibility workflows**

```ts
test("architect can move from release to deployment decision", async ({ page }) => {
  await page.goto("/overview");
  await page.getByRole("link", { name: "Kimi K3" }).click();
  await expect(page.getByText("Detected")).toBeVisible();
  await page.getByRole("link", { name: "Open planner" }).click();
  await page.getByLabel("Workspace").selectOption("workspace:dc");
  await page.getByRole("button", { name: "Calculate fit" }).click();
  await expect(page.getByText(/H200/)).toBeVisible();
  await expect(page.getByText("Assumptions")).toBeVisible();
});
```

Accessibility tests run axe on every top-level route with zero serious or
critical violations and verify keyboard-only navigation, focus restoration,
status text, table captions, and dialog labels. Visual tests cover 1440×1000,
1024×768, and 390×844 in light and dark mode.

- [ ] **Step 4: Add the release verification script**

```bash
#!/usr/bin/env bash
set -euo pipefail

uv run pytest
uv run ruff check src tests
uv run mypy src/radar
uv run radar intelligence-migrate --root .
uv run radar intelligence-shadow --root . --check
uv run radar export --root . --out _site

(
  cd frontend
  npm ci
  npm run generate:api
  git diff --exit-code -- src/api/generated
  npm test
  npm run typecheck
  npm run lint
  npm run build
  npx playwright test
)
```

Make the script executable. It must not mutate committed YAML/JSONL inputs
other than explicitly generated, diff-checked artifacts.

- [ ] **Step 5: Run the complete gate**

Run: `scripts/verify_intelligence_release.sh`

Expected:

- Python tests pass with coverage at or above 80%.
- Ruff and mypy pass.
- Migration is idempotent and shadow comparison is equivalent.
- Public static export succeeds and contains no workspaces.
- Generated TypeScript API types are clean.
- Frontend unit, type, lint, production build, Playwright, accessibility, and
  visual tests pass.

- [ ] **Step 6: Record cutover and architecture**

Update `CHANGELOG.md`, `docs/architecture.md`, and `docs/persistence.md` with
the canonical store, event mirror, lifecycle, scheduler modes, React/static
delivery, workspace behavior, legacy compatibility, and rollback procedure.
Rollback restores the previous Jinja root route while leaving canonical
ingestion and event logs intact.

- [ ] **Step 7: Commit final verification**

```bash
git add tests/e2e frontend/e2e scripts/verify_intelligence_release.sh \
  CHANGELOG.md docs/architecture.md docs/persistence.md
git commit -m "test: gate the intelligence platform release"
```

---

## Execution order and checkpoints

Execute tasks strictly in order. Tasks 1–5 establish contracts and execution
infrastructure. Tasks 6–10 establish trustworthy intelligence. Tasks 11–15
establish shared delivery. Tasks 16–20 build and cut over the product
experience. Tasks 21–22 establish freshness automation and release evidence.

Required checkpoints:

1. After Task 3: migration imports twice without changes.
2. After Task 9: no invalid lifecycle transition or uncited verification is
   possible.
3. After Task 15: API, MCP, feeds, webhooks, and snapshot share event IDs and
   facts.
4. After Task 20: live and static React surfaces pass before any legacy root
   route is removed.
5. After Task 22: the single release verification script is green.
