from fastapi import APIRouter, status

from api.deps import CurrentUser, Db, Now
from api.schemas.auth import Credentials, Me, Profile, RequestLink, Session, Verify
from api.services import auth as service

router = APIRouter(prefix="/auth", tags=["auth"])

# One body for every outcome of /auth/request: new account, known account, throttled.
ACCEPTED = {"detail": "If that address can receive mail, a link is on its way."}


@router.post("/request", status_code=status.HTTP_202_ACCEPTED)
def request_link(body: RequestLink, db: Db, now: Now) -> dict[str, str]:
    """Send a login link. Creates the account on first use.

    The response is identical whether or not the address is known. A different status or
    body for an unknown email is a user-enumeration oracle, and this endpoint is
    unauthenticated by definition.
    """
    service.request_link(db, body.email, now)
    return ACCEPTED


@router.post("/verify")
def verify(body: Verify, db: Db, now: Now) -> Session:
    return service.verify(db, body.token, now)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(body: Credentials, db: Db, now: Now) -> Session:
    """Create an account with a password (D31).

    An address that already has an account is refused, password or not: setting a
    password on someone else's magic-link account would be taking it over.
    """
    return service.signup(db, body.email, body.password, now)


@router.post("/login")
def login(body: Credentials, db: Db, now: Now) -> Session:
    """Unknown address, magic-link-only account and wrong password all answer the same."""
    return service.login(db, body.email, body.password, now)


@router.get("/me")
def me(user_id: CurrentUser, db: Db) -> Me:
    return service.me(db, user_id)


@router.get("/profile")
def read_profile(user_id: CurrentUser, db: Db) -> Profile:
    return service.read_profile(db, user_id)


@router.put("/profile")
def write_profile(body: Profile, user_id: CurrentUser, db: Db) -> Profile:
    """Merge, not replace.

    Intake saves one screen at a time and settings edits one field at a time, so an
    omitted key means "leave it alone" and an explicit null means "clear it". Full
    replacement would make the second intake screen wipe the first.

    Nothing here is logged. This is health-adjacent data and the only reason it is stored
    at all is that a consumer is expected later (D29).
    """
    return service.write_profile(db, user_id, body.model_dump(exclude_unset=True))
