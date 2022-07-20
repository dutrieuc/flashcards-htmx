from typing import Any, List, Optional

from uuid import UUID
from datetime import datetime
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import BaseModel

from flashcards_server.database import (
    get_async_session,
    Card as CardModel,
    Tag as TagModel,
    Fact as FactModel,
)
from flashcards_server.api.decks import router, valid_deck
from flashcards_server.api.facts import FactRead
from flashcards_server.api.tags import TagRead, TagCreate
from flashcards_server.users import current_active_user
from flashcards_server.schemas import UserRead


class CardCreate(BaseModel):
    question_id: UUID
    answer_id: UUID
    question_context_facts: Optional[List[UUID]]
    answer_context_facts: Optional[List[UUID]]
    tags: Optional[List[TagCreate]]


class CardPatch(BaseModel):
    question_id: Optional[UUID]
    answer_id: Optional[UUID]


class RelatedCard(BaseModel):
    id: UUID
    deck_id: UUID
    question: FactRead
    answer: FactRead
    question_context_facts: List[FactRead]
    answer_context_facts: List[FactRead]
    tags: List[TagRead]

    class Config:
        orm_mode = True


class RelatedCard(BaseModel):
    id: UUID
    deck_id: UUID
    question: FactRead
    answer: FactRead
    question_context_facts: List[FactRead]
    answer_context_facts: List[FactRead]
    tags: List[TagRead]
    relationship: str

    class Config:
        orm_mode = True


class CardRead(BaseModel):
    id: UUID
    deck_id: UUID
    question: FactRead
    answer: FactRead
    question_context_facts: List[FactRead]
    answer_context_facts: List[FactRead]
    tags: List[TagRead]
    related: Optional[List[RelatedCard]]

    class Config:
        orm_mode = True


class Review(BaseModel):
    id: UUID
    card_id: UUID
    result: Any
    algorithm: str
    datetime: datetime

    class Config:
        orm_mode = True


async def valid_card(
    session: Session, user: UserRead, deck_id: UUID, card_id: UUID
) -> CardModel:
    """
    Check that the card actually exists and belongs to the given (valid) deck.

    :param deck_id: the deck this card should belong to
    :param card_id: the card to check
    :returns: the card, if all check passes.
    :raises HTTPException if any check fails
    """
    valid_deck(session=session, user=user, deck_id=deck_id)
    card = await CardModel.get_one_async(session=session, object_id=card_id)
    if card is None or card.deck_id != deck_id:
        raise HTTPException(
            status_code=404, detail=f"Card with ID '{card_id}' not found"
        )
    return card


@router.get("/{deck_id}/cards", response_model=List[CardRead])
async def get_cards(
    deck_id: UUID,
    offset: int = 0,
    limit: int = 100,
    current_user: UserRead = Depends(current_active_user),
    session: Session = Depends(get_async_session),
):
    """
    Get all the cards for a deck (paginated, if needed).

    :param deck_id: the id of the deck this card belongs to
    :param offset: for pagination, index at which to start returning cards.
    :param limit: for pagination, maximum number of cards to return.
    :returns: List of cards.
    """
    valid_deck(session=session, user=current_user, deck_id=deck_id)
    stmt = (
        select(CardModel)
        .where(CardModel.deck_id == deck_id)
        .offset(offset)
        .limit(limit)
    )
    results = await session.scalars(stmt)
    db_cards = results.all()
    cards = []
    for card in db_cards:
        card.related = await card.related_cards_async(session)
        cards.append(card)
    return cards


@router.get("/{deck_id}/cards/{card_id}", response_model=CardRead)
async def get_card(
    deck_id: UUID,
    card_id: UUID,
    current_user: UserRead = Depends(current_active_user),
    session: Session = Depends(get_async_session),
):
    """
    Get all the details of one card.

    :param deck_id: the id of the deck this card belongs to
    :param card_id: the id of the card to get
    :returns: The details of the card.
    """
    card = await valid_card(
        session=session, user=current_user, deck_id=deck_id, card_id=card_id
    )
    card.related = await card.related_cards_async(session)
    return card


@router.post("/{deck_id}/cards", response_model=CardRead)
async def create_card(
    deck_id: UUID,
    card: CardCreate,
    current_user: UserRead = Depends(current_active_user),
    session: Session = Depends(get_async_session),
):
    """
    Creates a new card with the given data.

    :param deck_id: the id of the deck this card will belong to
    :param card: the details of the new card.
    :returns: The new card
    """
    valid_deck(session=session, user=current_user, deck_id=deck_id)

    card_data = card.dict()
    card_data["deck_id"] = deck_id
    tags = card_data.pop("tags", [])
    question_context = card_data.pop("question_context_facts", [])
    answer_context = card_data.pop("answer_context_facts", [])
    new_card = await CardModel.create_async(session=session, **card_data)

    if tags:
        for tag in tags:
            tag_object = await TagModel.get_by_name_async(session=session, name=tag["name"])
            if not tag_object:
                tag_object = await TagModel.create_async(session=session, name=tag["name"])
            new_card.assign_tag(session=session, tag_id=tag_object.id)

    if question_context:
        for fact in question_context:
            fact_object = await FactModel.get_one_async(session=session, object_id=fact)
            if not fact_object:
                raise HTTPException(
                    status_code=404, detail=f"Fact with ID '{fact}' not found"
                )
            new_card.assign_question_context(session=session, fact_id=fact)

    if answer_context:
        for fact in answer_context:
            fact_object = await FactModel.get_one_async(session=session, object_id=fact)
            if not fact_object:
                raise HTTPException(
                    status_code=404, detail=f"Fact with ID '{fact}' not found"
                )
            new_card.assign_answer_context(session=session, fact_id=fact)

    return new_card


@router.patch("/{deck_id}/cards/{card_id}", response_model=CardRead)
async def edit_card(
    deck_id: UUID,
    card_id: UUID,
    new_card_data: CardPatch,
    current_user: UserRead = Depends(current_active_user),
    session: Session = Depends(get_async_session),
):
    """
    Edits the details of the given card

    :param deck_id: the id of the deck this card belongs to
    :param card_id: the id of the card to edit
    :param new_card_data: the new details of the card. Can be partial.
    :returns: The modified card
    """
    original_data = valid_card(session=session, deck_id=deck_id, card_id=card_id)

    update_data = new_card_data.dict(exclude_unset=True)
    new_model = CardCreate(**vars(original_data)).copy(update=update_data)
    new_model_data = {
        key: value for key, value in new_model.dict().items() if value is not None
    }
    await CardModel.update_async(session=session, object_id=card_id, **new_model_data)
    return CardModel.get_one_async(session=session, object_id=card_id)


@router.get("/{deck_id}/cards/{card_id}/reviews", response_model=List[Review])
async def get_reviews(
    deck_id: UUID,
    card_id: UUID,
    current_user: UserRead = Depends(current_active_user),
    session: Session = Depends(get_async_session),
):
    """
    Get all the reviews done on this card.

    :param deck_id: the id of the deck this card belongs to
    :param card_id: the id of the card to get the reviews of
    :returns: The reviews of the card.
    """
    card = await valid_card(
        session=session, user=current_user, deck_id=deck_id, card_id=card_id
    )
    return card.reviews


@router.put("/{deck_id}/cards/{card_id}/tags/{tag_name}", response_model=CardRead)
async def assign_tag_to_card(
    deck_id: UUID,
    card_id: UUID,
    tag_name: str,
    current_user: UserRead = Depends(current_active_user),
    session: Session = Depends(get_async_session),
):
    """
    Assign this tag to the card.

    :param deck_id: the id of the deck this card belongs to
    :param card_id: the id of the card to edit
    :param tag_name: the tag to assign to this card
    :returns: The modified card
    """
    card = await valid_card(
        session=session, user=current_user, deck_id=deck_id, card_id=card_id
    )
    tag = await TagModel.get_by_name_async(session=session, name=tag["name"])
    if not tag:
        tag = await TagModel.create_async(session=session, name=tag_name)
    card.assign_tag(session=session, tag_id=tag.id)


@router.delete("/{deck_id}/cards/{card_id}/tags/{tag_name}", response_model=CardRead)
async def remove_tag_from_card(
    deck_id: UUID,
    card_id: UUID,
    tag_name: str,
    current_user: UserRead = Depends(current_active_user),
    session: Session = Depends(get_async_session),
):
    """
    Remove this tag from the card.

    :param deck_id: the id of the deck this card belongs to
    :param card_id: the id of the card to edit
    :param tag_name: the tag to remove from this card
    :returns: The modified card
    """
    card = await valid_card(
        session=session, user=current_user, deck_id=deck_id, card_id=card_id
    )
    tag = await TagModel.get_by_name_async(session=session, name=tag["name"])
    if not tag:
        raise HTTPException(status_code=404, detail=f"Tag '{tag_name}' doesn't exist.")
    card.remove_tag(session=session, tag_id=tag.id)


@router.put(
    "/{deck_id}/cards/{card_id}/context/question/{fact_id}", response_model=CardRead
)
async def assign_question_context_to_card(
    deck_id: UUID,
    card_id: UUID,
    fact_id: UUID,
    current_user: UserRead = Depends(current_active_user),
    session: Session = Depends(get_async_session),
):
    """
    Assign this fact as a context for the question of the card.

    :param deck_id: the id of the deck this card belongs to
    :param card_id: the id of the card to edit
    :param fact_id: the fact to assign as question context to this card
    :returns: The modified card
    """
    card = await valid_card(
        session=session, user=current_user, deck_id=deck_id, card_id=card_id
    )
    fact = await FactModel.get_one_async(session=session, object_id=fact_id)
    if not fact:
        raise HTTPException(
            status_code=404, detail=f"Fact with ID '{fact_id}' doesn't exist."
        )
    card.assign_question_context(session=session, fact_id=fact.id)


@router.delete(
    "/{deck_id}/cards/{card_id}/context/question/{fact_id}", response_model=CardRead
)
async def remove_question_context_from_card(
    deck_id: UUID,
    card_id: UUID,
    fact_id: UUID,
    current_user: UserRead = Depends(current_active_user),
    session: Session = Depends(get_async_session),
):
    """
    Remove this fact from the question context of the card.

    :param deck_id: the id of the deck this card belongs to
    :param card_id: the id of the card to edit
    :param fact_id: the id of the fact to remove from the question context
    :returns: The modified card
    """
    card = await valid_card(
        session=session, user=current_user, deck_id=deck_id, card_id=card_id
    )
    fact = await FactModel.get_one_async(session=session, object_id=fact_id)
    if not fact:
        raise HTTPException(
            status_code=404, detail=f"Fact with ID '{fact_id}' doesn't exist."
        )
    card.remove_question_context(session=session, fact_id=fact.id)


@router.put("/{deck_id}/cards/{card_id}/context/answer/{fact_id}", response_model=CardRead)
async def assign_answer_context_to_card(
    deck_id: UUID,
    card_id: UUID,
    fact_id: UUID,
    current_user: UserRead = Depends(current_active_user),
    session: Session = Depends(get_async_session),
):
    """
    Assign this fact as a context for the answer of the card.

    :param deck_id: the id of the deck this card belongs to
    :param card_id: the id of the card to edit
    :param fact_id: the fact to assign as answer context to this card
    :returns: The modified card
    """
    card = await valid_card(
        session=session, user=current_user, deck_id=deck_id, card_id=card_id
    )
    fact = await FactModel.get_one_async(session=session, object_id=fact_id)
    if not fact:
        raise HTTPException(
            status_code=404, detail=f"Fact with ID '{fact_id}' doesn't exist."
        )
    card.assign_answer_context(session=session, fact_id=fact.id)


@router.delete(
    "/{deck_id}/cards/{card_id}/context/answer/{fact_id}", response_model=CardRead
)
async def remove_answer_context_from_card(
    deck_id: UUID,
    card_id: UUID,
    fact_id: UUID,
    current_user: UserRead = Depends(current_active_user),
    session: Session = Depends(get_async_session),
):
    """
    Remove this fact from the answer context of the card.

    :param deck_id: the id of the deck this card belongs to
    :param card_id: the id of the card to edit
    :param fact_id: the id of the fact to remove from the answer context
    :returns: The modified card
    """
    card = await valid_card(
        session=session, user=current_user, deck_id=deck_id, card_id=card_id
    )
    fact = await FactModel.get_one_async(session=session, object_id=fact_id)
    if not fact:
        raise HTTPException(
            status_code=404, detail=f"Fact with ID '{fact_id}' doesn't exist."
        )
    card.remove_answer_context(session=session, fact_id=fact.id)


@router.put("/{deck_id}/cards/{card_id}/related", response_model=CardRead)
async def assign_tag_to_card(
    deck_id: UUID,
    card_id: UUID,
    related_card_id: UUID,
    relationship: str,
    current_user: UserRead = Depends(current_active_user),
    session: Session = Depends(get_async_session),
):
    """
    Create a relationship between these two cards.

    :param deck_id: the id of the deck this card belongs to
    :param card_id: the id of the card to edit
    :param card_id: the id of the related card
    :param relationship: the type of relationship between the cards
    :returns: The modified card
    """
    card = await valid_card(
        session=session, user=current_user, deck_id=deck_id, card_id=card_id
    )
    card.assign_related_card_async(session=session, card_id=related_card_id, relationship=relationship)
    card = await get_card(deck_id=deck_id, card_id=card_id, current_user=current_user, session=session)
    return card


@router.delete("/{deck_id}/cards/{card_id}/related", response_model=CardRead)
async def remove_related_card(
    deck_id: UUID,
    card_id: UUID,
    related_card_id: UUID,
    relationship: str,
    current_user: UserRead = Depends(current_active_user),
    session: Session = Depends(get_async_session),
):
    """
    Remove a relationship between these two cards.

    :param deck_id: the id of the deck this card belongs to
    :param card_id: the id of the card to edit
    :param card_id: the id of the related card
    :param relationship: the type of relationship between the cards
    :returns: The modified card
    """
    card = await valid_card(
        session=session, user=current_user, deck_id=deck_id, card_id=card_id
    )
    card.remove_related_card_async(session=session, card_id=related_card_id, relationship=relationship)
    card = await get_card(deck_id=deck_id, card_id=card_id, current_user=current_user, session=session)
    return card


@router.delete("/{deck_id}/cards/{card_id}")
async def delete_card(
    deck_id: UUID,
    card_id: UUID,
    current_user: UserRead = Depends(current_active_user),
    session: Session = Depends(get_async_session),
):
    """
    Removes the given card from this deck

    :param deck_id: the id of the deck to remove the card from
    :param card_id: the id of the card to delete
    :returns: None
    """
    await valid_card(session=session, user=current_user, deck_id=deck_id, card_id=card_id)
    CardModel.delete_async(session=session, object_id=card_id)
