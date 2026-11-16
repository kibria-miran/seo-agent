"""Typer entry point.

    seo-agent run --site profiles/site.json --no-llm

Default runs execute the deterministic pipeline. --agent opts in to the LLM
tool loop; both honour --with-sources (file-based GSC) and --with-scraping
(ToS-grey Suggest/SERP, off by default), and --with-drafts.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from src import config
from src.evals import load_scenarios, run_evals
from src.pipeline import load_profile, run_deterministic

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


@app.command()
def run(
    site: Path = typer.Option(
        Path("profiles/site.json"),
        "--site",
        help="Path to the site profile JSON.",
    ),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Deterministic mode: zero LLM calls, templates only.",
    ),
    with_sources: bool = typer.Option(
        False,
        "--with-sources",
        help="File-based sources (GSC CSV via SEO_AGENT_GSC_CSV). Never scrapes.",
    ),
    with_scraping: bool = typer.Option(
        False,
        "--with-scraping",
        help="ToS-grey Google Suggest / DuckDuckGo SERP scraping and competitor discovery. Off by default.",
    ),
    agent: bool = typer.Option(
        False,
        "--agent",
        help="Let the LLM tool loop orchestrate (requires NVIDIA_API_KEY).",
    ),
    with_drafts: bool = typer.Option(
        False,
        "--with-drafts",
        help="Write compliance-gated draft pages under out/<run-id>/drafts/.",
    ),
    fixture: Path | None = typer.Option(
        None,
        "--fixture",
        help="Audit fixture JSON; skips the network audit entirely.",
    ),
    run_id: str | None = typer.Option(None, "--run-id", help="Override the run id."),
    db_path: Path | None = typer.Option(None, "--db", help="Override out/state/seo.db."),
    out_root: Path | None = typer.Option(None, "--out", help="Override the out/ root."),
) -> None:
    """Audit the site, find keyword gaps, rank a backlog and write a report."""

    if agent and no_llm:
        console.print("[red]--agent and --no-llm are mutually exclusive[/red]")
        raise typer.Exit(code=2)

    profile = load_profile(site)
    if fixture is None:
        import os

        is_demo_profile = (
            profile.domain == config.PLACEHOLDER_DOMAIN
            and profile.fca_firm_ref == config.PLACEHOLDER_FCA_REF
        )
        if is_demo_profile and os.environ.get(config.ALLOW_DEMO_PROFILE_ENV) != "1":
            console.print(
                "[red]Refusing to crawl the placeholder demo profile[/red] "
                f"({profile.domain}, FCA {profile.fca_firm_ref})."
            )
            console.print(
                "Replace profiles/site.json with your real domain, money pages, "
                "target keywords, competitors, cities and FCA firm reference, "
                "or pass --fixture to run against an audit fixture. "
                f"Set {config.ALLOW_DEMO_PROFILE_ENV}=1 to acknowledge the demo values."
            )
            raise typer.Exit(code=2)
        if is_demo_profile:
            console.print(
                f"[yellow]Live crawl acknowledged against the placeholder demo profile "
                f"({config.ALLOW_DEMO_PROFILE_ENV}=1). This site is fictional.[/yellow]"
            )
    if not no_llm:
        console.print(
            "[yellow]No --no-llm flag set; running the deterministic template "
            "path. Agent mode (--agent) is available for the opt-in LLM tool "
            "loop.[/yellow]"
        )
    if fixture is None:
        console.print(
            f"[dim]Live audit of {profile.base_url} via vendored seoextract "
            f"({config.SEOEXTRACT_COMMIT[:8]}), max {config.MAX_OWN_PAGES} pages.[/dim]"
        )

    if with_sources:
        console.print(
            "[dim]File-based sources enabled: GSC CSV (SEO_AGENT_GSC_CSV if set). "
            "No scraping, no network calls to Google.[/dim]"
        )
    if with_scraping:
        console.print(
            "[yellow]ToS-grey scraping enabled: Google Suggest, DuckDuckGo HTML "
            "SERP, competitor discovery. Each HTTP call is throttled, cached and "
            "GET-only; results may be blocked or empty.[/yellow]"
        )

    if agent:
        from src.agent import AgentRunner
        from src.llm import LLMClient, LLMUnavailable

        try:
            llm = LLMClient.from_env()
        except LLMUnavailable as exc:
            console.print(f"[red]Agent mode unavailable:[/red] {exc}")
            raise typer.Exit(code=2) from exc
        runner = AgentRunner(
            llm,
            run_id=run_id,
            db_path=str(db_path) if db_path else None,
            out_root=str(out_root) if out_root else None,
            with_sources=with_sources,
            with_scraping=with_scraping,
            with_drafts=with_drafts,
        )
        report = runner.run(profile, fixture_path=fixture)
        console.print(
            f"[green]Agent run {report.run_id} complete[/green] · "
            f"score {report.site_score:.1f} ({report.grade}) · "
            f"{len(report.backlog)} backlog item(s) · status {report.status} · "
            f"llm_calls={report.budgets.get('llm_calls')} · "
            f"drafts={report.budgets.get('drafts')}"
        )
        if report.budgets.get("outputs"):
            console.print(f"Report: {report.budgets['outputs'].get('report', '(not written)')}")
        return

    report = run_deterministic(
        profile,
        fixture_path=fixture,
        run_id=run_id,
        db_path=db_path,
        out_root=out_root,
        with_sources=with_sources,
        with_scraping=with_scraping,
        with_drafts=with_drafts,
    )
    console.print(
        f"[green]Run {report.run_id} complete[/green] \u00b7 "
        f"score {report.site_score:.1f} ({report.grade}) \u00b7 "
        f"{len(report.backlog)} backlog item(s) \u00b7 status {report.status} \u00b7 "
        f"drafts={report.budgets.get('drafts')}"
    )
    outputs = report.budgets.get("outputs", {})
    if outputs:
        console.print(f"Report: {outputs.get('report', '(not written)')}")


@app.command("evals")
def evals_command(
    list_only: bool = typer.Option(
        False,
        "--list",
        help="Print scenario ids and titles, then exit.",
    ),
    extra: bool = typer.Option(
        False,
        "--extra",
        help="Run the extra scenarios in evals/extra/ instead of the frozen v1.2 eight.",
    ),
    all_scenarios: bool = typer.Option(
        False,
        "--all",
        help="Run both the frozen v1.2 eight and the evals/extra/ scenarios.",
    ),
) -> None:
    """Run the frozen v1.2 eight by default and write evals/results/evals-<ts>.json."""

    if extra and all_scenarios:
        console.print("[red]--extra and --all are mutually exclusive[/red]")
        raise typer.Exit(code=2)
    if extra:
        scenarios_dir = config.EXTRA_SCENARIOS_DIR
        include_extra = False
    else:
        scenarios_dir = None
        include_extra = all_scenarios
    if list_only:
        for scenario in load_scenarios(scenarios_dir, include_extra=include_extra):
            console.print(f"{scenario.id:5} {scenario.title}")
        return
    summary = run_evals(scenarios_dir, include_extra=include_extra)
    for result in summary["results"]:
        mark = "[green]PASS[/green]" if result["ok"] else "[red]FAIL[/red]"
        console.print(f"{mark} {result['id']:5} {result['title']}")
    console.print(
        f"[bold]{summary['passed']}/{summary['total']} scenarios passed[/bold] "
        f"({summary['failed']} failed)"
    )
    if summary["failed"]:
        raise typer.Exit(code=1)


@app.command("doctor")
def doctor(
    site: Path = typer.Option(
        Path("profiles/site.json"),
        "--site",
        help="Path to the site profile JSON.",
    ),
) -> None:
    """Local self-check for cron/systemd: profile, paths, vendored layer, key.

    Nothing here touches the network. Exits 2 on any FAIL.
    """

    import os
    import sys

    failures = 0

    def line(tag: str, message: str) -> None:
        colour = {"PASS": "green", "INFO": "dim", "WARN": "yellow", "FAIL": "red"}.get(tag, "white")
        console.print(f"[{colour}]{tag:4}[/{colour}] {message}")

    # 1. profile
    try:
        profile = load_profile(site)
        line("PASS", f"profile loads: {profile.domain} "
                     f"({len(profile.money_pages)} money page(s), "
                     f"{len(profile.target_keywords)} keywords, "
                     f"{len(profile.competitors)} competitors, "
                     f"FCA {profile.fca_firm_ref})")
        if (
            profile.domain == config.PLACEHOLDER_DOMAIN
            and profile.fca_firm_ref == config.PLACEHOLDER_FCA_REF
        ):
            line("WARN", "placeholder demo profile values are still in the profile; "
                         "replace before any live run (live run is refused without "
                         f"{config.ALLOW_DEMO_PROFILE_ENV}=1 or --fixture)")
    except Exception as exc:
        failures += 1
        line("FAIL", f"profile: {type(exc).__name__}: {exc}")
        profile = None

    # 2. money keywords resolvable
    if profile is not None:
        from src.pipeline import money_keywords_for

        money = money_keywords_for(profile)
        line("PASS", f"money keywords derive: {money}")

    # 3. output paths writable
    for path in (config.OUT_DIR, config.LOGS_DIR, config.DATA_DIR):
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            failures += 1
            line("FAIL", f"cannot create {path}: {exc}")
        else:
            line("PASS", f"writable: {path}")

    # 4. vendored audit layer imports and probes clean
    try:
        vendor = str(config.SEOEXTRACT_DIR)
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        from seoextract import core as _core
        from seoextract import models as _models

        from src.audit_adapter import probe_capabilities

        probe_capabilities(_models, _core)
        line("PASS", f"seoextract {config.SEOEXTRACT_VERSION} probe clean "
                     f"({config.SEOEXTRACT_COMMIT[:8]})")
    except Exception as exc:
        failures += 1
        line("FAIL", f"seoextract: {type(exc).__name__}: {exc}")

    # 5. LLM key (optional — the default path never needs it)
    if os.environ.get(config.NIM_API_KEY_ENV):
        line("INFO", f"{config.NIM_API_KEY_ENV} is set; --agent would work")
    else:
        line("INFO", f"{config.NIM_API_KEY_ENV} not set; --no-llm works, --agent does not")

    # 6. GSC export (optional demand signal)
    if os.environ.get("SEO_AGENT_GSC_CSV"):
        line("INFO", f"GSC CSV configured: {os.environ['SEO_AGENT_GSC_CSV']}")
    else:
        line("INFO", "SEO_AGENT_GSC_CSV not set; gsc_csv source will be skipped (dep_unmet)")

    if failures:
        console.print(f"[red]doctor found {failures} problem(s)[/red]")
        raise typer.Exit(code=2)
    console.print("[green]doctor: all checks passed[/green]")


@app.command("version")
def version() -> None:
    """Print the application and vendored audit-layer versions."""

    console.print(f"{config.APP_NAME} {config.APP_VERSION}")
    console.print(f"seoextract {config.SEOEXTRACT_VERSION} @ {config.SEOEXTRACT_COMMIT}")


if __name__ == "__main__":  # pragma: no cover
    app()
