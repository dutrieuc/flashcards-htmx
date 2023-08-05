from typing import Optional
from pathlib import Path
import shelve
import json
from copy import deepcopy

from jinja2 import Template
import starlette.status as status
from fastapi import APIRouter, Request, Depends, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates

from flashcards_htmx.app import template, database


templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter()


@router.get("/home", response_class=HTMLResponse)
async def home_page(request: Request, render=Depends(template("private/home.html"))):
    with shelve.open(database) as db:
        print([len(deck["cards"]) for deck in db["decks"].values()])
    return render(
        navbar_title="Home",
        searchable=True,
        new_item_endpoint=request.url_for("create_deck_page"),
        upload_item_endpoint=request.url_for("import_deck_page"),
        new_item_text="New Deck...",
    )


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(render=Depends(template("private/profile.html"))):
    # TODO actually get the profile information
    return render(navbar_title="My name")


@router.get("/study/{deck_id}", response_class=HTMLResponse)
async def study_page(deck_id: str, render=Depends(template("private/study.html"))):
    with shelve.open(database) as db:
        deck = db["decks"].get(deck_id, {})
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")
    return render(navbar_title=deck["name"], deck=deck, deck_id=deck_id)


@router.get("/decks/new", response_class=HTMLResponse)
async def create_deck_page(render=Depends(template("private/deck.html"))):
    with shelve.open(database) as db:
        id = len(db["decks"]) + 1
    return render(
        navbar_title="New Deck",
        deck={"name": "", "description": "", "algorithm": "Random"},
        deck_id= id
    )


@router.get("/decks/import", response_class=HTMLResponse)
async def import_deck_page(render=Depends(template("private/import.html"))):
    return render()


@router.post('/decks/import', response_class=RedirectResponse)
async def import_deck_endpoint(file: UploadFile):
    try:
        contents = await file.read()
        deck = json.loads(contents)
        with shelve.open(database) as db:
            db["decks"][str(len(db["decks"])+1)] = deck
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='There was an error importing the deck',
        )
    finally:
        await file.close()
    return RedirectResponse(router.url_path_for("home_page"), status_code=status.HTTP_302_FOUND)


@router.get("/decks/{deck_id}/export", response_class=FileResponse)
async def export_deck_endpoint(request: Request):
    with shelve.open(database) as db:
        deck = deepcopy(db["decks"].get(request.path_params["deck_id"], {}))
        if not deck:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        
        # Remove reviews and renderings
        deck["cards"] = {
            card_id: {key: val for key, val in card.items() if key != "reviews" and not key.startswith("rendered_")} 
            for card_id, card in deck["cards"].items()
            }
        

        path = Path(__file__).parent.parent / f"tmp/{deck['name']}.json"

        with open(path, 'w') as file:
            json.dump(deck, file, indent=4)
    return FileResponse(path, media_type='application/octet-stream', filename=f"{deck['name']}.json")


@router.get("/decks/{deck_id}", response_class=HTMLResponse)
async def edit_deck_page(deck_id: str, render=Depends(template("private/deck.html"))):
    with shelve.open(database) as db:
        deck = db["decks"].get(deck_id, {})
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")
    return render(navbar_title=deck["name"], deck=deck, deck_id=deck_id)


@router.post("/decks/{deck_id}", response_class=RedirectResponse)
async def save_deck_endpoint(deck_id: str, request: Request):
    async with request.form() as form:
        with shelve.open(database) as db:
            if not "decks" in db:
                db["decks"] = {}
            db["decks"][deck_id] = {
                **db["decks"].get(deck_id, {"cards": {}}),
                "name": form["name"],
                "description": form["description"],
                "algorithm": form["algorithm"]
            }
    return RedirectResponse(
        request.url_for("home_page"), status_code=status.HTTP_302_FOUND
    )


@router.get("/decks/{deck_id}/delete", response_class=RedirectResponse)
async def delete_deck_endpoint(
    request: Request,
    deck_id: str
):
    with shelve.open(database) as db:
        if deck_id not in db["decks"]:
            raise HTTPException(status_code=404, detail="Deck not found")
        del db["decks"][deck_id]
        
    return RedirectResponse(request.url_for("home_page"), status_code=status.HTTP_302_FOUND)


@router.get("/decks/{deck_id}/cards", response_class=HTMLResponse)
async def cards_page(
    deck_id: str, request: Request, render=Depends(template("private/cards.html"))
):
    with shelve.open(database) as db:
        deck = db["decks"].get(deck_id, {})
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")
    return render(
        navbar_title=deck["name"],
        deck=deck,
        deck_id=deck_id,
        searchable=True,
        new_item_endpoint=request.url_for("create_card_page", deck_id=deck_id),
        new_item_text="New Card...",
    )


@router.get("/decks/{deck_id}/cards/new", response_class=HTMLResponse)
async def create_card_page(deck_id: str, render=Depends(template("private/card.html"))):
    with shelve.open(database) as db:
        deck = db["decks"].get(deck_id, {})
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")
        
        id = len(db["decks"].get(deck_id, {}).get("cards", {})) + 1
        card_templates = db["templates"]
        for template in card_templates.values():
            template["rendered_form"] = Template(template["form"]).render(question={}, answer={}, preview={})
    return render(
        navbar_title=deck["name"],
        deck=deck,
        deck_id=deck_id,
        card={
            "id": id,
            "data": {
                "question": {},
                "answer": {},
                "preview": {},
            },
            "tags": [],
            "type": "Q/A",
            "reviews": {},
        },
        card_id=id,
        card_templates=card_templates
    )


@router.get("/decks/{deck_id}/cards/{card_id}", response_class=HTMLResponse)
async def edit_card_page(
    deck_id: str, card_id: str, render=Depends(template("private/card.html"))
):
    with shelve.open(database) as db:
        deck = db["decks"].get(deck_id, {})
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")
        
        card_templates = db["templates"]
        card = deck["cards"].get(card_id, {})
        if not card:
            raise HTTPException(status_code=404, detail="Card not found")
        
        for template in card_templates.values():
            template["rendered_form"] = Template(template["form"]).render(**card["data"])

    return render(
        navbar_title=deck["name"],
        deck=deck,
        deck_id=deck_id,
        card=card,
        card_id=card_id,
        card_templates=card_templates
    )


@router.post("/decks/{deck_id}/cards/{card_id}", response_class=RedirectResponse)
async def save_card_endpoint(deck_id: str, card_id: Optional[str], request: Request):
    async with request.form() as form:
        with shelve.open(database) as db:
            deck = db["decks"].get(deck_id, {})
            deck["cards"][card_id] = {
                **deck["cards"].get(card_id, {"reviews": {}}),
                "data": {
                    "question": {
                        key[len("question."):] : value for key, value in form.items() if key.startswith("question.")
                    },
                    "answer": {
                        key[len("answer."):] : value for key, value in form.items() if key.startswith("answer.")
                    },
                    "preview": {
                        key[len("preview."):]: value for key, value in form.items() if key.startswith("preview.")
                    }
                },
                "tags": [tag.strip() for tag in form["tags"].split(",") if tag.strip()],
                "type": form["type"],
            }

    return RedirectResponse(
        request.url_for("cards_page", deck_id=deck_id), status_code=status.HTTP_302_FOUND
    )


@router.get("/decks/{deck_id}/cards/{card_id}/delete", response_class=RedirectResponse)
async def delete_card_endpoint(
    request: Request,
    deck_id: str,
    card_id: str,
):
    with shelve.open(database) as db:
        if deck_id not in db["decks"]:
            raise HTTPException(status_code=404, detail="Deck not found")
        if card_id not in db["decks"][deck_id]["cards"]:
            raise HTTPException(status_code=404, detail="Card not found")
        del db["decks"][deck_id]["cards"][card_id]
        
    return RedirectResponse(request.url_for("cards_page", deck_id=deck_id), status_code=status.HTTP_302_FOUND)


@router.post("/logout", response_class=RedirectResponse)
async def logout_page(request: Request):
    return RedirectResponse(
        request.url_for("home_page"), status_code=status.HTTP_302_FOUND
    )