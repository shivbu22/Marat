"""Seed and index World Knowledge (Last 6 Months) into Marat workspaces and RAG vaults."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.workspaces.manager import get_workspace_manager
from src.rag.store import get_rag

def seed():
    mgr = get_workspace_manager()
    rag = get_rag()
    
    file_path = Path("data/knowledge/world_events_last_6_months.md")
    if not file_path.exists():
        print(f"Error: {file_path} not found")
        return
        
    content = file_path.read_bytes()
    filename = "World_Events_Last_6_Months.md"
    
    # 1. Create or get dedicated workspace
    ws_slug = "world-knowledge-6m"
    ws = mgr.get_workspace_by_slug(ws_slug)
    if not ws:
        ws = mgr.create_workspace(
            name="Global Intelligence (Last 6 Months)",
            slug=ws_slug,
            description="Comprehensive briefing on AI breakthroughs, geopolitics, SpaceX/NASA missions, quantum computing, and economic shifts over the last 6 months.",
            system_prompt="You are Mara, expert global intelligence analyst. Provide comprehensive, evidence-grounded insights into recent world events, technology breakthroughs, and geopolitical developments from the last 6 months."
        )
        print(f"Created dedicated workspace: {ws.name} ({ws.id})")
    else:
        print(f"Found existing workspace: {ws.name} ({ws.id})")

    # Seed threads for dedicated workspace
    threads = mgr.list_threads(ws.id)
    if not threads:
        th1 = mgr.create_thread(ws.id, name="AI & Silicon Frontier")
        th2 = mgr.create_thread(ws.id, name="Space, Quantum & Deep Tech")
        th3 = mgr.create_thread(ws.id, name="Global Geopolitics & Policy")
        print("Created starter threads in dedicated workspace.")
        
    # Ingest document into dedicated workspace
    doc, chunks = mgr.add_document(
        ws.id, 
        filename, 
        content, 
        extra_metadata={"category": "world_knowledge_last_6_months"}
    )
    rag.add_chunks(chunks, collection_name=ws.vector_collection)
    print(f"Indexed {len(chunks)} chunks into workspace collection '{ws.vector_collection}'")

    # 2. Also index into Default Workspace so general queries have instant access
    default_ws = mgr.get_workspace_by_slug("default")
    if default_ws:
        doc_def, chunks_def = mgr.add_document(
            default_ws.id,
            filename,
            content,
            extra_metadata={"category": "world_knowledge_last_6_months"}
        )
        rag.add_chunks(chunks_def, collection_name=default_ws.vector_collection)
        print(f"Indexed {len(chunks_def)} chunks into default workspace collection '{default_ws.vector_collection}'")

    # 3. Also index into main research_vault
    rag.add_chunks(chunks, collection_name="research_vault")
    print("Indexed chunks into core research_vault.")
    print("World Knowledge (Last 6 Months) successfully loaded into Marat!")

if __name__ == "__main__":
    seed()
