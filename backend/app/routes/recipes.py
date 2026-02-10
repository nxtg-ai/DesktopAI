"""Recipe routes for pre-built desktop automation sequences."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from ..deps import autonomy, store
from ..recipes import BUILTIN_RECIPES, match_recipes
from ..schemas import AutonomyStartRequest

router = APIRouter()


@router.get("/api/recipes")
async def list_recipes() -> dict:
    from ..desktop_context import DesktopContext

    current_event = await store.current()
    ctx = DesktopContext.from_event(current_event) if current_event else None
    matched = match_recipes(ctx)
    return {
        "recipes": [asdict(r) for r in matched],
        "total_available": len(BUILTIN_RECIPES),
    }


@router.post("/api/recipes/{recipe_id}/run")
async def run_recipe(recipe_id: str) -> dict:
    recipe = next((r for r in BUILTIN_RECIPES if r.recipe_id == recipe_id), None)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")

    start_req = AutonomyStartRequest(
        objective=recipe.description,
        max_iterations=len(recipe.steps) + 5,
        parallel_agents=1,
        auto_approve_irreversible=False,
    )
    run = await autonomy.start(start_req)
    return {"run_id": run.run_id, "recipe": asdict(recipe)}
