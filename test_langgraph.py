import asyncio
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

class MyState(TypedDict):
    status: str
    counter: int

def node_a(state):
    return {"status": "pending", "counter": state.get("counter", 0) + 1}

def human(state):
    return {}

def router(state):
    print("ROUTER CALLED, status is:", state.get("status"))
    if state.get("status") == "approved":
        return "node_b"
    return "node_c"

def node_b(state):
    print("NODE B")
    return {}

def node_c(state):
    print("NODE C")
    return {}

builder = StateGraph(MyState)
builder.add_node("node_a", node_a)
builder.add_node("human", human)
builder.add_node("node_b", node_b)
builder.add_node("node_c", node_c)

builder.add_edge(START, "node_a")
builder.add_edge("node_a", "human")
builder.add_conditional_edges("human", router, {"node_b": "node_b", "node_c": "node_c"})
builder.add_edge("node_b", END)
builder.add_edge("node_c", END)

async def main():
    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer, interrupt_before=["human"])
    config = {"configurable": {"thread_id": "1"}}
    
    await graph.ainvoke({"status": "init", "counter": 0}, config)
    state = await graph.aget_state(config)
    print("State after interrupt:", state.values)
    
    graph2 = builder.compile(checkpointer=checkpointer, interrupt_before=[])
    await graph2.aupdate_state(config, {"status": "approved"}, as_node="human")
    
    state2 = await graph2.aget_state(config)
    print("State after update:", state2.values)
    
    await graph2.ainvoke(None, config)

asyncio.run(main())
