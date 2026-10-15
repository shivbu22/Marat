#!/usr/bin/env python3
"""CLI for MARAT — Multi-Agent Research Assistant Technology."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .config import get_settings
from .graph.workflow import get_graph
from .reverse_engineer.agent import run_target_analysis
from .workspaces.manager import get_workspace_manager
from .mcp.hypervisor import get_mcp_hypervisor

MARAT_BANNER = """[bold cyan]
 __  __    _    ____      _  _____ 
|  \\/  |  / \\  |  _ \\    / \\|_   _|
| |\\/| | / _ \\ | |_) |  / _ \\ | |  
| |  | |/ ___ \\|  _ <  / ___ \\| |  
|_|  |_/_/   \\_\\_| \\_\\/_/   \\_\\_|  
[/bold cyan]
[bold bright_magenta]MARAT v2 — Multi-Agent Research & Reverse Engineering Platform[/bold bright_magenta]
[dim italic]Featuring Mara, your clever scholar red panda research companion[/dim italic]
"""

app = typer.Typer(
    add_completion=False,
    help="MARAT — Multi-Agent Research & Reverse Engineering Platform featuring Mara",
)
console = Console()


@app.command()
def research(
    topic: str = typer.Argument(..., help="Research topic or question"),
    focus: str = typer.Option("broad", help="Focus mode: broad | deep | verify | reverse_engineer"),
    video: str = typer.Option("", "--video", "-v", help="Optional YouTube lecture URL or audio/video file path"),
    target: str = typer.Option("", "--target", "-t", help="Optional binary, ASAR, APK, WASM, or code path to reverse-engineer"),
    workspace: str = typer.Option("default", "--workspace", "-w", help="Workspace ID for isolated memory"),
    save: bool = typer.Option(True, help="Save report to disk"),
):
    """Run a full multi-agent research and reverse-engineering pipeline."""
    s = get_settings()
    console.print(MARAT_BANNER)
    video_line = f"\n[bold yellow]Video Ingest:[/] {video}" if video else ""
    target_line = f"\n[bold red]Reverse Engineering Target:[/] {target}" if target else ""
    ws_line = f"\n[bold green]Workspace:[/] {workspace}"
    console.print(
        Panel.fit(
            f"[bold cyan]Topic:[/] {topic}\n[bold magenta]Focus:[/] {focus}{video_line}{target_line}{ws_line}\n[dim]Companion: Mara 🐾[/dim]",
            title="🐾 MARAT Mission Dispatch",
            border_style="cyan",
        )
    )

    graph = get_graph()
    initial = {
        "topic": topic,
        "focus_mode": focus,
        "video_url": video,
        "target_path": target,
        "workspace_id": workspace,
        "sub_questions": [],
        "findings": [],
        "re_findings": [],
        "mcp_tools_used": [],
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
            task = progress.add_task("Planning investigation…", total=None)

            async for event in graph.astream(initial, stream_mode="updates"):
                for node, update in event.items():
                    for k, v in update.items():
                        if k in ("findings", "raw_search_notes", "sources_used", "re_findings") and isinstance(v, list):
                            final_state.setdefault(k, []).extend(v)
                        else:
                            final_state[k] = v

                    if node == "planner":
                        sqs = update.get("sub_questions") or []
                        progress.update(
                            task,
                            description=f"[cyan]Planner complete:[/] {len(sqs)} sub-questions identified",
                        )
                    elif node == "reverse_engineer":
                        re_res = update.get("re_findings") or []
                        progress.update(
                            task,
                            description=f"[red]Reverse Engineer complete:[/] {len(re_res)} targets analyzed",
                        )
                    elif node == "researcher":
                        n_findings = len(final_state.get("findings", []))
                        progress.update(
                            task,
                            description=f"[magenta]Researcher complete:[/] {n_findings} findings discovered",
                        )
                    elif node == "fact_checker":
                        fcs = update.get("fact_checks") or []
                        verified = sum(1 for fc in fcs if fc.get("status") in ("VERIFIED", "PARTIALLY_VERIFIED"))
                        progress.update(
                            task,
                            description=f"[yellow]Fact-checker complete:[/] {verified}/{len(fcs)} claims verified",
                        )
                    elif node == "writer":
                        progress.update(task, description="[blue]Writer complete:[/] Draft synthesized")
                    elif node == "reviewer":
                        status = update.get("status", "")
                        count = update.get("review_count", 1)
                        if status == "done":
                            progress.update(task, description=f"[green]Review approved after cycle {count}[/]")
                        else:
                            progress.update(
                                task,
                                description=f"[yellow]Revision requested (cycle {count})[/]",
                            )

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
        console.print(f"[green]Saved report → {path}[/]")


@app.command("reverse-engineer")
@app.command("re")
def reverse_engineer_cmd(
    target: str = typer.Argument(..., help="Path to binary, ASAR, APK, WASM, or code folder to inspect"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON results"),
):
    """Deep inspection of a binary, Electron ASAR, Android APK, WebAssembly, or source tree."""
    console.print(MARAT_BANNER)
    console.print(f"[bold red]Reverse Engineering Target:[/] {target}")

    with console.status("[bold green]Inspecting binary layout, headers, and strings…[/]"):
        result = run_target_analysis(target)

    if "error" in result:
        console.print(f"[red]Inspection failed:[/] {result['error']}")
        raise typer.Exit(1)

    if json_output:
        console.print_json(json.dumps(result))
        return

    data = result.get("data", {})
    fmt = result.get("format", "UNKNOWN")

    console.print(
        Panel.fit(
            f"[bold cyan]File:[/] {result.get('file_name')}\n"
            f"[bold magenta]Format:[/] {fmt}\n"
            f"[bold yellow]Evidence ID:[/] {result.get('evidence_id')}\n"
            f"[bold green]Summary:[/] {result.get('summary')}",
            title="🛠️ Static Reverse Engineering Dossier",
            border_style="red",
        )
    )

    # Sections table if PE / ELF
    sections = data.get("sections")
    if sections:
        table = Table(title="Executable Sections & Entropy", border_style="cyan")
        table.add_column("Section", style="bold")
        table.add_column("Virtual Size", justify="right")
        table.add_column("Raw Size", justify="right")
        table.add_column("Entropy", justify="right")
        table.add_column("Flags")
        for sec in sections[:15]:
            ent_color = "red" if sec.get("entropy", 0) > 7.1 else "green"
            table.add_row(
                sec.get("name", ""),
                f"{sec.get('virtual_size', 0):,}",
                f"{sec.get('raw_size', 0):,}",
                f"[{ent_color}]{sec.get('entropy', 0):.2f}[/]",
                ", ".join(sec.get("characteristics", [])),
            )
        console.print(table)

    # Imports preview
    imports = data.get("imports")
    if imports:
        console.print(f"\n[bold]Imported Libraries ({len(imports)}):[/]")
        for imp in imports[:10]:
            console.print(f"  • [cyan]{imp.get('library')}[/]")

    # ASAR IPC Channels if Electron
    ipc_channels = data.get("ipc_channels")
    if ipc_channels:
        table = Table(title="Electron IPC Communication Channels", border_style="magenta")
        table.add_column("Channel", style="bold green")
        table.add_column("Type", style="yellow")
        table.add_column("Source File", style="dim")
        for ch in ipc_channels[:15]:
            table.add_row(ch.get("channel", ""), ch.get("type", ""), ch.get("file", ""))
        console.print(table)

    # API Endpoints
    endpoints = data.get("api_endpoints")
    if endpoints:
        console.print(f"\n[bold]Discovered API Endpoints ({len(endpoints)}):[/]")
        for ep in endpoints[:15]:
            console.print(f"  • [green]{ep}[/]")


@app.command("workspaces")
def workspaces_cmd():
    """List all isolated knowledge workspaces."""
    mgr = get_workspace_manager()
    workspaces = mgr.list_workspaces()
    table = Table(title="🐾 MARAT Knowledge Workspaces", border_style="green")
    table.add_column("Name", style="bold cyan")
    table.add_column("Slug", style="dim")
    table.add_column("Documents", justify="right")
    table.add_column("Vector Collection")
    for ws in workspaces:
        table.add_row(ws.name, ws.slug, str(ws.documents_count), ws.vector_collection)
    console.print(table)


@app.command("mcp")
def mcp_cmd():
    """List and test registered MCP servers."""
    hyp = get_mcp_hypervisor()
    servers = hyp.list_servers()
    table = Table(title="⚡ MARAT MCP Hypervisor Servers", border_style="yellow")
    table.add_column("Server", style="bold cyan")
    table.add_column("Command", style="magenta")
    table.add_column("Args", style="dim")
    table.add_column("Status")
    for s in servers:
        test_res = hyp.test_server(s.name)
        status_str = "[green]Connected[/]" if test_res.get("status") == "connected" else "[red]Offline[/]"
        table.add_row(s.name, s.command, " ".join(s.args), status_str)
    console.print(table)


@app.command("ingest-video")
def ingest_video_cmd(
    source: str = typer.Argument(..., help="YouTube video URL or local audio/video file path"),
    title: str = typer.Option("", help="Optional title for the lecture or talk"),
):
    """Transcribe and index a video lecture into the ChromaDB Knowledge Vault."""
    from .tools.video import index_lecture_in_rag, ingest_video

    console.print(MARAT_BANNER)
    console.print(f"[bold cyan]Transcribing & indexing media:[/] {source}")

    with console.status("[bold green]Extracting speech & generating timestamps…[/]"):
        lecture = ingest_video(source, title=title)

    if not lecture or not lecture.segments:
        console.print("[red]Failed to transcribe media or no speech detected.[/]")
        raise typer.Exit(1)

    count = index_lecture_in_rag(lecture)
    console.print(
        Panel.fit(
            f"[bold green]Title:[/] {lecture.title}\n"
            f"[bold cyan]Source Type:[/] {lecture.source_type}\n"
            f"[bold yellow]Segments:[/] {len(lecture.segments)} timestamped entries\n"
            f"[bold magenta]Indexed Chunks in Vault:[/] {count} blocks",
            title="🐾 Video Lecture Ingested",
            border_style="green",
        )
    )
    if lecture.segments:
        console.print("\n[bold]Preview (First 3 Segments):[/]")
        for seg in lecture.segments[:3]:
            console.print(f"  [cyan]{seg.timestamp}[/] {seg.text}")


@app.command("ingest-world-knowledge")
def ingest_world_knowledge_cmd():
    """Ingest curated global developments (AI, Space, Quantum, Geopolitics) from the last 6 months into workspaces."""
    import subprocess
    console.print(MARAT_BANNER)
    console.print("[bold cyan]Ingesting World Knowledge (Last 6 Months) into Vector Vaults…[/]")
    script_path = Path("data/seed_world_knowledge.py")
    if not script_path.exists():
        console.print("[red]Seed script not found.[/]")
        raise typer.Exit(1)
    
    with console.status("[bold green]Chunking and embedding global intelligence briefings…[/]"):
        import runpy
        runpy.run_path(str(script_path), run_name="__main__")
    console.print("[bold green]✔ Ingested and embedded global knowledge across all workspaces![/]")



@app.command()
def serve(
    host: str = typer.Option(None, help="Host"),
    port: int = typer.Option(None, help="Port"),
):
    """Start the MARAT FastAPI server."""
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
