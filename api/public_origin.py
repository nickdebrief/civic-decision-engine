"""Trusted public-origin policy for discovery metadata and public aliases."""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit


CANONICAL_PUBLIC_ORIGIN_ENV = "CDE_CANONICAL_PUBLIC_ORIGIN"
CLARITY_ENABLED_ENV = "CDE_CLARITY_ENABLED"
GOOGLE_ANALYTICS_ENABLED_ENV = "CDE_GOOGLE_ANALYTICS_ENABLED"
ANALYTICS_TEST_MODE_ENV = "CDE_ANALYTICS_TEST_MODE"
ANALYTICS_TEST_ORIGIN_ENV = "CDE_ANALYTICS_TEST_ORIGIN"
ANALYTICS_TEST_GOOGLE_MEASUREMENT_ID_ENV = "CDE_ANALYTICS_TEST_GOOGLE_MEASUREMENT_ID"
ANALYTICS_TEST_CLARITY_PROJECT_ID_ENV = "CDE_ANALYTICS_TEST_CLARITY_PROJECT_ID"
DEFAULT_CANONICAL_PUBLIC_ORIGIN = "https://civicdecisionengine.ie"
CANONICAL_ALIAS_HOSTS = frozenset(
    {
        "www.civicdecisionengine.ie",
        "civic-decision-engine-production.up.railway.app",
    }
)
_CANONICAL_TAG = re.compile(r"\s*<link\b[^>]*\brel=[\"']canonical[\"'][^>]*>", re.I)
_GOVERNED_REPORT_PUBLICATION_PATH = re.compile(
    r"/governed-reports/gr-[1-9][0-9]*\.json\Z"
)
CLARITY_PROJECT_ID = "ym9fkxdm29"
GOOGLE_ANALYTICS_MEASUREMENT_ID = "G-8405RVT76Q"
_GOOGLE_ANALYTICS_MEASUREMENT_ID = re.compile(r"G-[A-Z0-9]{6,32}\Z")
_CLARITY_PROJECT_ID = re.compile(r"[a-z0-9]{10}\Z")
# Analytics is deliberately narrower than indexability.  In particular, it
# excludes APIs, governed artefacts, verification, and record/detail pages.
_GOOGLE_ANALYTICS_ELIGIBLE_PUBLIC_PATHS = frozenset({"/"})
_CLARITY_ELIGIBLE_PUBLIC_PATHS = frozenset(
    {
        "/",
        "/archive",
        "/associations",
        "/collections",
        "/conditions",
        "/conditions/map",
        "/determinations",
        "/stats",
        "/stats/timeline",
        "/traceability",
        "/transmissions",
    }
)
_ANALYTICS_CONSENT_CONTROL = (
    '<script data-cde-clarity-consent="1" type="text/javascript">'
    '(function(){"use strict";'
    'var key="cde_optional_analytics_preferences_v2",legacyKey="cde_optional_analytics_consent_v1",maxAge=7776000000,clarityEnabled=__CLARITY_ENABLED__,googleEnabled=__GOOGLE_ENABLED__,generation=0;'
    'function clear(){try{window.localStorage.removeItem(key);window.localStorage.removeItem(legacyKey)}catch(e){}eraseGoogle();eraseClarity()}'
    'function stored(){try{var raw=window.localStorage.getItem(key);if(window.localStorage.getItem(legacyKey)!==null){clear();return null}if(!raw){return null}var v=JSON.parse(raw);if(v.v!==1||typeof v.expires!=="number"||v.expires<=Date.now()||typeof v.ga!=="boolean"||typeof v.clarity!=="boolean"){clear();return null}return v}catch(e){clear();return null}}'
    'function save(v){try{window.localStorage.setItem(key,JSON.stringify({v:1,expires:Date.now()+maxAge,ga:!!v.ga,clarity:!!v.clarity}))}catch(e){}}'
    'function mask(){if(document.body){document.body.setAttribute("data-clarity-mask","true")}}'
    'function erase(pattern){var labels=location.hostname.split("."),scopes=[""];for(var i=0;i<labels.length-1;i++){var d=labels.slice(i).join(".");scopes.push(";domain="+d,";domain=."+d)}document.cookie.split(";").forEach(function(c){var n=c.split("=",1)[0].trim();if(pattern.test(n)){scopes.forEach(function(scope){document.cookie=n+"=;expires=Thu, 01 Jan 1970 00:00:00 GMT;Max-Age=0;path=/"+scope+";SameSite=Lax"})}})}'
    'function eraseGoogle(){erase(/^_ga(?:_|$)/)}function eraseClarity(){erase(/^_cl(?:ck|sk)$/)}'
    'function removeLoaders(selector){document.querySelectorAll(selector).forEach(function(node){node.remove()})}function current(token,name){var value=stored();return token===generation&&!!(value&&value[name])}'
    'function loadGoogle(token){if(!googleEnabled||!current(token,"ga")||document.querySelector("script[data-cde-google-loader=\\"1\\"]")){return};'
    'window.dataLayer=window.dataLayer||[];window.gtag=window.gtag||function(){window.dataLayer.push(arguments)};'
    'var pageLocation=__GOOGLE_PAGE_LOCATION__,pageTitle="Civic Decision Engine";'
    'window.gtag("consent","default",{analytics_storage:"granted",ad_storage:"denied",ad_user_data:"denied",ad_personalization:"denied"});window.gtag("js",new Date());'
    'window.gtag("config","__GOOGLE_MEASUREMENT_ID__",{anonymize_ip:true,send_page_view:false,page_location:pageLocation,page_title:pageTitle,page_referrer:"",ignore_referrer:true});'
    'window.gtag("event","page_view",{page_location:pageLocation,page_title:pageTitle,page_referrer:"",ignore_referrer:true});'
    'var g=document.createElement("script");g.async=true;g.src="https://www.googletagmanager.com/gtag/js?id=__GOOGLE_MEASUREMENT_ID__";g.setAttribute("data-cde-google-loader","1");g.onload=function(){if(!current(token,"ga")){removeLoaders("script[data-cde-google-loader=\\"1\\"]")}};if(current(token,"ga")){document.head.appendChild(g)}}'
    'function loadClarity(token){if(!clarityEnabled||!current(token,"clarity")||document.querySelector("script[data-cde-clarity-loader=\\"1\\"]")){return};'
    'var q=window.clarity||function(){(q.q=q.q||[]).push(arguments)};window.clarity=q;'
    'q("consentv2",{ad_Storage:"denied",analytics_Storage:"granted"});'
    'var s=document.createElement("script");s.async=true;s.src="https://www.clarity.ms/tag/__CLARITY_PROJECT_ID__";'
    's.setAttribute("data-cde-clarity-loader","1");s.onload=function(){if(!current(token,"clarity")){removeLoaders("script[data-cde-clarity-loader=\\"1\\"]")}};if(current(token,"clarity")){document.head.appendChild(s)}}'
    'function load(v){var token=generation;mask();if(v&&v.ga){loadGoogle(token)}if(v&&v.clarity){loadClarity(token)}}'
    'function stop(previous,next){generation+=1;if(!next.ga){removeLoaders("script[data-cde-google-loader=\\"1\\"]");eraseGoogle();if(typeof window.gtag==="function"){window.gtag("consent","update",{analytics_storage:"denied",ad_storage:"denied",ad_user_data:"denied",ad_personalization:"denied"})}}if(!next.clarity){removeLoaders("script[data-cde-clarity-loader=\\"1\\"]");if(typeof window.clarity==="function"){window.clarity("consentv2",{ad_Storage:"denied",analytics_Storage:"denied"})}eraseClarity()}}'
    'function words(){var all=window.CDE_I18N&&window.CDE_I18N.TRANSLATIONS,lang=document.documentElement.lang||"en",catalog=all&&all[lang];return function(k){if(catalog&&catalog[k]){return catalog[k]}console.error("[CDE i18n] Missing analytics translation: "+k+" for "+lang);return "["+k+"]"}}'
    'function ready(){mask();var t=words();'
    'var open=document.createElement("button");open.type="button";open.className="cde-analytics-entry cde-analytics-entry-button";open.setAttribute("data-cde-analytics-text","analytics_preferences");open.setAttribute("data-cde-clarity-preferences","1");'
    'var panel=document.createElement("section");panel.className="cde-analytics-dialog";panel.hidden=true;panel.setAttribute("role","dialog");panel.setAttribute("aria-modal","false");panel.setAttribute("aria-labelledby","cde-analytics-preferences-title");panel.setAttribute("data-cde-clarity-dialog","1");'
    'panel.innerHTML="<h2 id=\\"cde-analytics-preferences-title\\" data-cde-analytics-text=\\"analytics_preferences_label\\"></h2><p data-cde-analytics-text=\\"analytics_description\\"></p><div data-cde-analytics-choice-list></div><p class=\\"cde-analytics-disabled-status\\" hidden data-cde-google-disabled><span data-cde-analytics-text=\\"analytics_ga_choice\\"></span>: <span data-cde-analytics-text=\\"analytics_provider_disabled\\"></span></p><p class=\\"cde-analytics-disabled-status\\" hidden data-cde-clarity-disabled><span data-cde-analytics-text=\\"analytics_clarity_choice\\"></span>: <span data-cde-analytics-text=\\"analytics_provider_disabled\\"></span></p><div class=\\"cde-analytics-actions\\"><button class=\\"cde-analytics-action\\" type=\\"button\\" data-cde-analytics-save data-cde-analytics-text=\\"analytics_save_choices\\"></button><button class=\\"cde-analytics-action\\" type=\\"button\\" data-cde-analytics-decline data-cde-analytics-text=\\"analytics_decline_both\\"></button></div><p><a href=\\"/privacy\\" data-cde-analytics-text=\\"analytics_privacy_notice\\"></a></p>";'
    'var choices=panel.querySelector("[data-cde-analytics-choice-list]");choices.innerHTML=(googleEnabled?"<label class=\\"cde-analytics-choice\\"><input type=\\"checkbox\\" data-cde-ga-choice> <span data-cde-analytics-text=\\"analytics_ga_choice\\"></span></label>":"")+(clarityEnabled?"<label class=\\"cde-analytics-choice\\"><input type=\\"checkbox\\" data-cde-clarity-choice> <span data-cde-analytics-text=\\"analytics_clarity_choice\\"></span></label>":"");document.body.appendChild(open);document.body.appendChild(panel);'
    'function translate(){t=words();document.querySelectorAll("[data-cde-analytics-text]").forEach(function(el){el.textContent=t(el.getAttribute("data-cde-analytics-text"))});open.setAttribute("aria-label",t("analytics_preferences"))}translate();document.addEventListener("cde-i18n-applied",translate);'
    'function showChoices(){var v=stored()||{ga:false,clarity:false},ga=panel.querySelector("[data-cde-ga-choice]"),clarity=panel.querySelector("[data-cde-clarity-choice]"),gaDisabled=panel.querySelector("[data-cde-google-disabled]"),clarityDisabled=panel.querySelector("[data-cde-clarity-disabled]");if(ga){ga.checked=v.ga}if(clarity){clarity.checked=v.clarity}gaDisabled.hidden=googleEnabled;clarityDisabled.hidden=clarityEnabled;panel.hidden=false;(googleEnabled?ga:(clarityEnabled?clarity:panel.querySelector("[data-cde-analytics-decline]"))).focus()}function hide(){panel.hidden=true}open.addEventListener("click",showChoices);'
    'function apply(next){var previous=stored();save(next);stop(previous,next);hide();window.location.reload()}'
    'panel.querySelector("[data-cde-analytics-save]").addEventListener("click",function(){var ga=panel.querySelector("[data-cde-ga-choice]"),clarity=panel.querySelector("[data-cde-clarity-choice]");apply({ga:!!(ga&&ga.checked),clarity:!!(clarity&&clarity.checked)})});'
    'panel.querySelector("[data-cde-analytics-decline]").addEventListener("click",function(){apply({ga:false,clarity:false})});'
    'var current=stored();if(current){load(current);hide()}else if(googleEnabled||clarityEnabled){showChoices()}else{hide()}}'
    'if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",ready)}else{ready()}})();'
    '</script>'
)
_ANALYTICS_I18N_SCRIPT = '<script src="/static/translations.js" data-cde-analytics-i18n="1"></script>'
_ANALYTICS_CONTROL_STYLE = (
    '<style data-cde-analytics-style="1">'
    '.cde-analytics-entry{position:fixed;right:1rem;bottom:1rem;z-index:2147483000;display:flex;gap:.6rem;align-items:center;max-width:calc(100vw - 2rem);padding:.7rem;background:#07111f;color:#f3f8ff;border:1px solid #8fd3ff;border-radius:.65rem;box-shadow:0 .5rem 1.5rem rgba(0,0,0,.45)}'
    '.cde-analytics-entry a,.cde-analytics-entry button,.cde-analytics-dialog a{color:#d4efff;text-decoration:underline;text-underline-offset:.16em}.cde-analytics-entry button,.cde-analytics-action{font:inherit;cursor:pointer;border:1px solid #8fd3ff;border-radius:.4rem;padding:.5rem .7rem;background:#102a42;color:#f3f8ff}.cde-analytics-entry button:hover,.cde-analytics-action:hover{background:#19486f}.cde-analytics-entry button:focus-visible,.cde-analytics-action:focus-visible,.cde-analytics-dialog a:focus-visible{outline:3px solid #fff;outline-offset:3px}'
    '.cde-analytics-dialog{position:fixed;right:1rem;bottom:4.8rem;z-index:2147483001;width:min(34rem,calc(100vw - 2rem));max-height:calc(100vh - 6rem);overflow:auto;padding:1rem;background:#07111f;color:#f3f8ff;border:2px solid #8fd3ff;border-radius:.7rem;box-shadow:0 .5rem 1.5rem rgba(0,0,0,.5)}.cde-analytics-dialog h2{margin-top:0}.cde-analytics-actions{display:flex;flex-wrap:wrap;gap:.6rem;margin:.9rem 0}.cde-analytics-choice{display:flex;align-items:center;gap:.65rem;min-height:2.75rem;margin:.35rem 0;cursor:pointer}.cde-analytics-choice input{inline-size:1.2rem;block-size:1.2rem;flex:0 0 auto;accent-color:#8fd3ff}.cde-analytics-choice input:focus-visible{outline:3px solid #fff;outline-offset:3px}.cde-analytics-choice input:disabled+span{opacity:.72}.cde-analytics-disabled-status{margin:.4rem 0;color:#d4efff}.cde-analytics-choice[hidden],.cde-analytics-disabled-status[hidden]{display:none}@media(max-width:38rem){.cde-analytics-entry{left:1rem;right:1rem;justify-content:space-between;flex-wrap:wrap}.cde-analytics-dialog{bottom:6.8rem}.cde-analytics-action{flex:1 1 12rem}}</style>'
)
_ANALYTICS_PREFERENCES_CLEAR_CONTROL = (
    '<script data-cde-analytics-preferences-clear="1" type="text/javascript">'
    '(function(){"use strict";'
    'var key="cde_optional_analytics_preferences_v2",legacyKey="cde_optional_analytics_consent_v1";'
    'function erase(pattern){var labels=location.hostname.split("."),scopes=[""];for(var i=0;i<labels.length-1;i++){var d=labels.slice(i).join(".");scopes.push(";domain="+d,";domain=."+d)}document.cookie.split(";").forEach(function(c){var n=c.split("=",1)[0].trim();if(pattern.test(n)){scopes.forEach(function(scope){document.cookie=n+"=;expires=Thu, 01 Jan 1970 00:00:00 GMT;Max-Age=0;path=/"+scope+";SameSite=Lax"})}})}'
    'function clear(){try{window.localStorage.removeItem(key);window.localStorage.removeItem(legacyKey)}catch(e){}erase(/^_ga(?:_|$)/);erase(/^_cl(?:ck|sk)$/)}'
    'function ready(){var entry=document.createElement("section"),open=document.createElement("button"),panel=document.createElement("section"),fallback={analytics_preferences:"Privacy preferences",analytics_preferences_label:"Privacy preferences",analytics_providers_disabled:"Analytics providers are currently disabled.",analytics_clear_preferences:"Clear saved analytics preferences",analytics_privacy_notice:"Read the privacy notice"};entry.className="cde-analytics-entry";entry.setAttribute("aria-label","Privacy preferences");open.type="button";open.setAttribute("data-cde-analytics-preferences","1");open.setAttribute("data-cde-analytics-text","analytics_preferences");panel.className="cde-analytics-dialog";panel.hidden=true;panel.setAttribute("role","dialog");panel.setAttribute("aria-modal","false");panel.setAttribute("aria-labelledby","cde-analytics-preferences-title");panel.setAttribute("data-cde-analytics-disabled-panel","1");panel.innerHTML="<h2 id=\\"cde-analytics-preferences-title\\" data-cde-analytics-text=\\"analytics_preferences_label\\"></h2><p class=\\"cde-analytics-disabled-status\\" data-cde-analytics-text=\\"analytics_providers_disabled\\"></p><button class=\\"cde-analytics-action\\" type=\\"button\\" data-cde-analytics-clear-preferences=\\"1\\" data-cde-analytics-text=\\"analytics_clear_preferences\\"></button><p><a href=\\"/privacy\\" data-cde-analytics-text=\\"analytics_privacy_notice\\"></a></p>";function translate(){var all=window.CDE_I18N&&window.CDE_I18N.TRANSLATIONS,lang=document.documentElement.lang||"en",catalog=all&&all[lang];function word(k){return(catalog&&catalog[k])||fallback[k]||k}document.querySelectorAll("[data-cde-analytics-text]").forEach(function(node){node.textContent=word(node.getAttribute("data-cde-analytics-text"))});open.setAttribute("aria-label",word("analytics_preferences"))}document.addEventListener("cde-i18n-applied",translate);open.addEventListener("click",function(){panel.hidden=false;panel.querySelector("[data-cde-analytics-clear-preferences]").focus()});panel.querySelector("[data-cde-analytics-clear-preferences]").addEventListener("click",function(){clear();window.location.reload()});entry.appendChild(open);document.body.appendChild(entry);document.body.appendChild(panel);translate()}'
    'if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",ready)}else{ready()}})();'
    '</script>'
)


def canonical_public_origin() -> str:
    """Return the configured, trusted HTTPS origin without a trailing slash."""
    value = os.getenv(CANONICAL_PUBLIC_ORIGIN_ENV, DEFAULT_CANONICAL_PUBLIC_ORIGIN)
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise RuntimeError("canonical_public_origin_invalid")
    return f"https://{parsed.netloc}"


def canonical_url(path: str) -> str:
    if not path.startswith("/"):
        raise ValueError("canonical_path_invalid")
    return f"{canonical_public_origin()}{path}"


def clarity_is_enabled() -> bool:
    """Return whether optional Clarity controls are operationally enabled.

    The default is intentionally off.  Setting the flag to any value other
    than the explicit ``1`` is an immediate fail-closed kill switch.
    """
    return os.getenv(CLARITY_ENABLED_ENV, "0") == "1"


def google_analytics_is_enabled() -> bool:
    """Return whether optional Google Analytics is operationally enabled."""
    return os.getenv(GOOGLE_ANALYTICS_ENABLED_ENV, "0") == "1"


def analytics_identifier_configuration() -> tuple[str | None, str | None]:
    """Return trusted analytics IDs, failing closed for incomplete test mode.

    Production IDs are used only when test mode is absent.  Test mode is a
    deployment configuration decision: it relies on the configured canonical
    origin, never the request ``Host`` or forwarded headers.
    """
    if os.getenv(ANALYTICS_TEST_MODE_ENV) != "1":
        return GOOGLE_ANALYTICS_MEASUREMENT_ID, CLARITY_PROJECT_ID

    configured_origin = os.getenv(ANALYTICS_TEST_ORIGIN_ENV)
    google_id = os.getenv(ANALYTICS_TEST_GOOGLE_MEASUREMENT_ID_ENV)
    clarity_id = os.getenv(ANALYTICS_TEST_CLARITY_PROJECT_ID_ENV)
    if not configured_origin or not google_id or not clarity_id:
        return None, None
    try:
        test_origin = _strict_https_origin(configured_origin)
    except RuntimeError:
        return None, None

    # Exact trusted-config equality prevents a request Host header from
    # selecting test identifiers.  Production and its fixed aliases can never
    # be a test origin, even when an environment is misconfigured.
    if test_origin != canonical_public_origin() or _is_production_origin(test_origin):
        return None, None
    if (
        not _GOOGLE_ANALYTICS_MEASUREMENT_ID.fullmatch(google_id)
        or not _CLARITY_PROJECT_ID.fullmatch(clarity_id)
        or google_id == GOOGLE_ANALYTICS_MEASUREMENT_ID
        or clarity_id == CLARITY_PROJECT_ID
    ):
        return None, None
    return google_id, clarity_id


def _strict_https_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise RuntimeError("analytics_test_origin_invalid")
    return f"https://{parsed.netloc}"


def _is_production_origin(origin: str) -> bool:
    hostname = urlsplit(origin).hostname
    if hostname is None:
        return True
    normalized = hostname.lower()
    return normalized in {
        "civicdecisionengine.ie",
        *CANONICAL_ALIAS_HOSTS,
    } or "civicdecisionengine" in normalized.replace("-", "")


def is_public_indexable_path(path: str) -> bool:
    exact = {
        "/",
        "/archive",
        "/api/docs",
        "/associations",
        "/collections",
        "/conditions",
        "/conditions/map",
        "/determinations",
        "/documents",
        "/graph",
        "/patterns",
        "/records",
        "/stats",
        "/stats/timeline",
        "/traceability",
        "/transmissions",
    }
    if path in exact:
        return True
    if _GOVERNED_REPORT_PUBLICATION_PATH.fullmatch(path):
        return True
    return path.startswith(
        (
            "/conditions/",
            "/determinations/",
            "/documents/",
            "/records/",
            "/transmissions/",
            "/verify/",
        )
    )


def is_clarity_eligible_public_path(path: str) -> bool:
    """Return whether a no-query public page may offer optional analytics."""
    return path in _CLARITY_ELIGIBLE_PUBLIC_PATHS


def is_google_analytics_eligible_public_path(path: str) -> bool:
    """Return whether a reviewed query-free public page may offer GA."""
    return path in _GOOGLE_ANALYTICS_ELIGIBLE_PUBLIC_PATHS


def is_analytics_eligible_public_path(path: str) -> bool:
    """Return whether any optional provider may offer local controls here."""
    return (
        is_google_analytics_eligible_public_path(path)
        or is_clarity_eligible_public_path(path)
    )


def google_analytics_effectively_enabled() -> bool:
    """Return GA enablement after trusted measurement-ID validation.

    A switch alone never makes GA available in test mode; incomplete or
    mismatched trusted configuration must fail closed.
    """
    google_id, _ = analytics_identifier_configuration()
    return google_analytics_is_enabled() and google_id is not None


def privacy_notice_google_analytics_status() -> str:
    """Return a trusted configuration-aware GA status for the privacy notice.

    This contains no identifiers and deliberately describes loading conditions,
    not provider cookies or a particular visitor's processing destination.
    """
    return (
        "Google Analytics loading is enabled only on the query-free home page after "
        "a valid affirmative choice. A saved refusal or no choice keeps it off."
        if google_analytics_effectively_enabled()
        else "Google Analytics loading is currently disabled. A saved browser "
        "preference does not itself enable Google Analytics; loading requires both "
        "a valid affirmative choice and a separate operational enablement."
    )


def public_alias_redirect_location(host: str, path: str, query: bytes) -> str | None:
    """Return a fixed-origin redirect location for approved public aliases only."""
    normalized_host = host.lower().split(":", 1)[0]
    if normalized_host not in CANONICAL_ALIAS_HOSTS:
        return None
    location = canonical_url(path)
    if query:
        location += "?" + query.decode("latin-1")
    return location


def inject_canonical_link(html: bytes, path: str) -> bytes:
    """Replace any existing canonical tag with exactly one trusted canonical link."""
    text = html.decode("utf-8")
    text = _CANONICAL_TAG.sub("", text)
    head = re.search(r"<head(?:\s[^>]*)?>", text, re.I)
    if head is None:
        return html
    link = f'<link rel="canonical" href="{canonical_url(path)}">'
    return (text[: head.end()] + link + text[head.end() :]).encode("utf-8")


def inject_public_html_head(html: bytes, path: str) -> bytes:
    """Add one consent-gated analytics control to an eligible public page.

    The control contains no external ``script src``.  It only appends a
    provider loader after a visitor has affirmatively selected that optional
    provider; rejection leaves public access intact and withdrawal clears the
    preference before a clean reload.  When both providers are operationally
    disabled, an identifier-free local clear-preferences control remains
    available on the same eligible routes.
    """
    canonicalized = inject_canonical_link(html, path)
    if not is_analytics_eligible_public_path(path):
        return canonicalized
    text = canonicalized.decode("utf-8")
    if (
        'data-cde-clarity-consent="1"' in text
        or 'data-cde-analytics-preferences-clear="1"' in text
    ):
        return canonicalized
    canonical_tag = _CANONICAL_TAG.search(text)
    if canonical_tag is None:
        return canonicalized
    translation = "" if 'src="/static/translations.js"' in text else _ANALYTICS_I18N_SCRIPT
    styling = "" if 'data-cde-analytics-style="1"' in text else _ANALYTICS_CONTROL_STYLE
    if not (clarity_is_enabled() or google_analytics_is_enabled()):
        return (
            text[: canonical_tag.end()]
            + translation
            + styling
            + _ANALYTICS_PREFERENCES_CLEAR_CONTROL
            + text[canonical_tag.end() :]
        ).encode("utf-8")

    google_id, clarity_id = analytics_identifier_configuration()
    clarity_enabled = clarity_is_enabled() and clarity_id is not None
    google_enabled = (
        google_analytics_effectively_enabled()
        and is_google_analytics_eligible_public_path(path)
    )
    if not (clarity_enabled or google_enabled):
        return (
            text[: canonical_tag.end()]
            + translation
            + styling
            + _ANALYTICS_PREFERENCES_CLEAR_CONTROL
            + text[canonical_tag.end() :]
        ).encode("utf-8")
    control = _ANALYTICS_CONSENT_CONTROL.replace(
        "__CLARITY_ENABLED__", str(clarity_enabled).lower()
    ).replace("__GOOGLE_ENABLED__", str(google_enabled).lower()).replace(
        "__GOOGLE_MEASUREMENT_ID__", google_id if google_enabled else ""
    ).replace("__CLARITY_PROJECT_ID__", clarity_id if clarity_enabled else "").replace(
        "__GOOGLE_PAGE_LOCATION__",
        json.dumps(canonical_url(path)) if google_enabled else "null",
    )
    return (
        text[: canonical_tag.end()]
        + translation
        + styling
        + control
        + text[canonical_tag.end() :]
    ).encode("utf-8")
