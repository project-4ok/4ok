from __future__ import annotations

from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import Integer, String, Text

from gcb.storage.models.base import Base


class ConnectorStateRow(Base):
    __tablename__ = "connector_states"

    connector_name: Mapped[str] = mapped_column(String, primary_key=True)
    state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default="")


class ConnectorJobRunRow(Base):
    __tablename__ = "connector_job_runs"
    __table_args__ = (
        Index(
            "uq_connector_job_runs_running_connector",
            "connector_name",
            unique=True,
            sqlite_where=text("status = 'running'"),
            postgresql_where=text("status = 'running'"),
        ),
    )

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    connector_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[str] = mapped_column(String, nullable=False, default="")
    finished_at: Mapped[str] = mapped_column(String, nullable=False, default="")
    input_state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    output_state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    raw_output_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
