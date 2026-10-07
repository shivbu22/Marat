#!/usr/bin/env python3
"""CLI for Multi-Agent Research Assistant."""

from __future__ import annotations

import asyncio
import time

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from .config import get_settings
from .graph.workflow import get_graph

MARAT_BANNER = """[bold cyan]
 __  __    _    ____      _  _____ 
|  \\/  |  / \\  |  _ \\    / \\|_   _|
| |\\/| | / _ \\ | |_) |  / _ \\ | |  
| |  | |/ ___ \\|  _ <  / ___ \\| |  
|_|  |_/_/   \\_\\_| \\_\\/_/   \\_\\_|  
[/bold cyan]
[bold bright_magenta]🐾 MARAT — Multi-Agent Research Assistant Technology[/bold bright_magenta]
[dim italic]Featuring Mara, your intelligent research companion[/dim italic]
"""

app = typer.Typer(
    add_completion=False,
    help="MARAT — Multi-Agent Research Assistant Technology featuring Mara 🐾",
)
console = Console()


@app.command()
def research(
    topic: str = typer.Argument(..., help="Research topic or question"),
    focus: str = typer.Option("broad", help="Focus mode: broad | deep | verify"),
    save: bool = typer.Option(True, help="Save report to disk"),
):
    """Run a full multi-agent research pipeline on a topic."""
    s = get_settings()
    console.print(MARAT_BANNER)
    console.print(
        Panel.fit(
            f"[bold cyan]Topic:[/] {topic}\n[bold magenta]Focus:[/] {focus}\n[dim]Companion: Mara 🐾[/dim]",
            title="🐾 MARAT Mission Dispatch",
            border_style="cyan",
        )
    )

    graph = get_graph()
    initial = {
        "topic": topic,
        "focus_mode": focus,
        "sub_questions": [],
        "findings": [],
        "raw_search_notes": [],
        "fact_checks": [],
        "draft_report": "",
        "final_report": "",
        "review_count": 0,
        "review_feedback": "",
        "status": "planning",
        "error": "",
        "sources_used": [],
    }

    start = time.time()

    async def run():
        final_state = dict(initial)
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Planning research…", total=None)

            async for event in graph.astream(initial, stream_mode="updates"):
                for node, update in event.items():
                    for k, v in update.items():
                        if k in ("findings", "raw_search_notes", "sources_used") and isinstance(
                            v, list
                        ):
                            final_state[k] = final_state.get(k, []) + v
                        else:
                            final_state[k] = v

                    if node == "planner":
                        n = len(update.get("sub_questions") or [])
                        progress.update(
                            task, description=f"Planned {n} sub-questions → researching…"
                        )
                    elif node == "researcher":
                        n = len(update.get("findings") or [])
                        progress.update(task, description=f"Gathered {n} findings → fact-checking…")
                    elif node == "fact_checker":
                        progress.update(
                            task, description="Fact-checking complete → writing report…"
                        )
                    elif node == "writer":
                        progress.update(task, description="Draft written → reviewing…")
                    elif node == "reviewer":
                        rc = update.get("review_count", 0)
                        if update.get("status") == "done":
                            progress.update(task, description="Report approved ✓")
                        else:
                            progress.update(task, description=f"Revision requested (cycle {rc})…")

        return final_state

    try:
        result = asyncio.run(run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    elapsed = time.time() - start
    report = result.get("final_report") or result.get("draft_report") or "(empty report)"

    console.print()
    console.print(Markdown(report))
    console.print()
    console.print(
        f"[dim]Status: {result.get('status')} | "
        f"Findings: {len(result.get('findings') or [])} | "
        f"Sources: {len(result.get('sources_used') or [])} | "
        f"Reviews: {result.get('review_count', 0)} | "
        f"Time: {elapsed:.1f}s[/]"
    )

    if save:
        out_dir = s.save_reports_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in topic)[:50]
        path = out_dir / f"{int(time.time())}_{safe}.md"
        path.write_text(report, encoding="utf-8")
        console.print(f"[green]Saved → {path}[/]")


@app.command()
def serve(
    host: str = typer.Option(None, help="Host"),
    port: int = typer.Option(None, help="Port"),
):
    """Start the FastAPI server."""
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "src.api.main:app",
        host=host or s.api_host,
        port=port or s.api_port,
        reload=False,
    )


if __name__ == "__main__":
    app()
