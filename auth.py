"""
auth.py — Session-based login gate for Procurement Health Check.

Usage in app.py:
    from auth import require_login
    require_login()   # call after apply_styles(), before any content

Credentials are read exclusively from st.secrets["auth"]["username"] and
st.secrets["auth"]["password"]. They are NEVER hard-coded here.
"""

import hmac
import time

import streamlit as st

from branding import render_login_page, render_legal_footer, APP_TITLE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_ATTEMPTS    = 5    # failed attempts before lockout
_LOCKOUT_SECONDS = 30   # lockout duration in seconds

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _init_state() -> None:
    """Ensure all auth-related session_state keys exist."""
    defaults = {
        "authenticated":        False,
        "auth_username":        "",
        "auth_failed_attempts": 0,
        "auth_locked_until":    0.0,
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


def _check_credentials(username: str, password: str) -> bool:
    """Return True when *username* and *password* match st.secrets.

    Uses hmac.compare_digest to prevent timing attacks.
    """
    try:
        expected_user = st.secrets["auth"]["username"]
        expected_pass = st.secrets["auth"]["password"]
    except KeyError:
        st.error(
            "Authentication secrets are not configured. "
            "Add [auth] username and password to .streamlit/secrets.toml "
            "or the Streamlit Cloud secrets dashboard."
        )
        st.stop()

    user_ok = hmac.compare_digest(username.strip(), expected_user.strip())
    pass_ok = hmac.compare_digest(password, expected_pass)
    return user_ok and pass_ok


def _render_login_form() -> None:
    """Render the enterprise two-column login page and handle submission."""

    # render_login_page draws the left panel and returns the right Streamlit column
    right_col = render_login_page(lockout_message=None, form_html_placeholder="")

    with right_col:
        # Card heading (HTML for precise typography)
        st.markdown(
            "<div class='phc-signin-eyebrow'>Reviewer access</div>"
            "<div class='phc-signin-title'>Sign in</div>"
            "<div class='phc-signin-sub'>Use the credentials provided with the "
            "submission to explore the application.</div>",
            unsafe_allow_html=True,
        )

        # Lockout check
        now = time.time()
        remaining = st.session_state["auth_locked_until"] - now
        if remaining > 0:
            st.warning(
                f"Too many failed attempts. Please wait "
                f"**{int(remaining) + 1} seconds** before trying again.",
                icon="🔒",
            )
            st.stop()

        # Login form
        with st.form("login_form", clear_on_submit=False, border=False):
            st.text_input("Username", key="_login_user", autocomplete="username")
            st.text_input("Password", key="_login_pass",
                          type="password", autocomplete="current-password")
            submitted = st.form_submit_button(
                "Sign in", width="stretch", type="primary"
            )

        st.markdown(
            "<div class='phc-signin-note'>🔒 Access is limited to authorised reviewers. "
            "Five failed attempts lock sign-in for 30 seconds.</div>",
            unsafe_allow_html=True,
        )

    if submitted:
        username = st.session_state.get("_login_user", "")
        password = st.session_state.get("_login_pass", "")
        if _check_credentials(username, password):
            st.session_state["authenticated"]        = True
            st.session_state["auth_username"]        = username.strip()
            st.session_state["auth_failed_attempts"] = 0
            st.session_state["auth_locked_until"]    = 0.0
            st.rerun()
        else:
            st.session_state["auth_failed_attempts"] += 1
            attempts = st.session_state["auth_failed_attempts"]
            if attempts >= _MAX_ATTEMPTS:
                st.session_state["auth_locked_until"] = time.time() + _LOCKOUT_SECONDS
                st.error(
                    f"Too many failed attempts. "
                    f"The form is locked for {_LOCKOUT_SECONDS} seconds.",
                    icon="🔒",
                )
            else:
                remaining_attempts = _MAX_ATTEMPTS - attempts
                st.error(
                    f"Invalid username or password. "
                    f"{remaining_attempts} attempt(s) remaining before lockout.",
                    icon="🚫",
                )

    # Legal footer below both panels
    render_legal_footer()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def require_login() -> None:
    """Gate all app content behind the enterprise login page.

    Call this immediately after ``apply_styles()`` in ``app.py``.
    If the session is not authenticated, the login page is shown and
    ``st.stop()`` is called so nothing else renders.

    Once authenticated, this function returns normally.
    """
    _init_state()

    if not st.session_state["authenticated"]:
        _render_login_form()
        st.stop()


def render_signout_button() -> None:
    """Render a 'Sign out' button in the sidebar.

    Call this inside the ``with st.sidebar:`` block in ``app.py``.
    Clears authentication state and reruns on click.
    """
    username = st.session_state.get("auth_username", "")
    if username:
        st.caption(f"Signed in as **{username}**")
    if st.button("Sign out", width="stretch"):
        # Clear auth state
        st.session_state["authenticated"] = False
        st.session_state["auth_username"] = ""
        # Clear all fetched data so the next user starts with a blank slate
        for _key in (
            "records", "is_cached", "raw_count", "dept_name", "keyword",
            "all_dept_records", "all_dept_cached", "all_dept_skipped",
            "cmp_records", "cmp_cached", "cmp_skipped",
        ):
            st.session_state.pop(_key, None)
        # Clear any cached AI briefs (keys prefixed with "ai_brief_")
        for _key in [k for k in st.session_state if k.startswith("ai_brief_")]:
            del st.session_state[_key]
        st.rerun()
