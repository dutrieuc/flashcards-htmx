import starlette.status as status

from typing import Annotated

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse

import flashcards_api_client
from flashcards_api_client.apis.tags import auth_api
from flashcards_api_client.model.body_auth_jwt_login_auth_jwt_login_post import (
    BodyAuthJwtLoginAuthJwtLoginPost,
)


from flashcards_htmx.app import template


router = APIRouter()
configuration = flashcards_api_client.Configuration(host="http://localhost:8001")


@router.get("/", response_class=HTMLResponse)
async def landing_page(render=Depends(template("public/landing-page.html"))):
    return render()


@router.get("/login", response_class=HTMLResponse)
async def login_page(render=Depends(template("public/login.html"))):
    return render()


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(render=Depends(template("public/signup.html"))):
    return render()


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(render=Depends(template("public/reset-password.html"))):
    return render()


@router.post("/login", response_class=RedirectResponse)
async def login_action(
    username: Annotated[str, Form()], password: Annotated[str, Form()], request: Request
):
    with flashcards_api_client.ApiClient(configuration) as api_client:
        auth_instance = auth_api.AuthApi(api_client)
        body = BodyAuthJwtLoginAuthJwtLoginPost(
            grant_type="password",
            username=username,
            password=password,
            scope="",
            # FIXME
            client_id="client_id_example",
            client_secret="client_secret_example",
        )
        try:
            # Auth:Jwt.Login
            api_response = auth_instance.auth_jwt_login(
                body=body,
            )
        except flashcards_api_client.ApiException as e:
            print("Exception when calling AuthApi->auth_jwt_login: %s\n" % e)

        response = RedirectResponse(
            request.url_for("home_page"), status_code=status.HTTP_303_SEE_OTHER
        )
        response.set_cookie(
            key="Authorization",
            value=api_response.body.get("access_token"),
            httponly=True,
            secure=True,
        )
        return response


@router.post("/signup", response_class=RedirectResponse)
async def signup_action(request: Request):
    # FIXME Actually do the signup!
    return RedirectResponse(
        request.url_for("home_page"), status_code=status.HTTP_302_FOUND
    )


@router.post("/reset-password", response_class=RedirectResponse)
async def reset_password_action(request: Request):
    # FIXME Actually do the password reset!
    return RedirectResponse(
        request.url_for("home_page"), status_code=status.HTTP_302_FOUND
    )
