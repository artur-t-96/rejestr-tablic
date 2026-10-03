from django.urls import path

from registry import account_invitation_views, session_views
from registry import views as v
from registry.pool_import_views import import_pools
from registry.record_import_views import import_records

urlpatterns = [
    path("", v.public, name="public"),
    path("logowanie/", v.login_email, name="login_email"),
    path("logowanie/kod/", v.login_code, name="login_code"),
    path("wyloguj/", v.logout_view, name="logout"),
    path("panel/", v.dashboard, name="dashboard"),
    path("panel/wnioski/", v.requests_list, name="requests_list"),
    path("panel/wnioski/nowy/", v.request_new, name="request_new"),
    path("panel/wnioski/<uuid:uuid>/", v.request_detail, name="request_detail"),
    path(
        "panel/wnioski/<uuid:uuid>/<str:action>/",
        v.request_action,
        name="request_action",
    ),
    path("panel/ewidencja/", v.records_list, name="records_list"),
    path("panel/ewidencja/<uuid:uuid>/", v.record_detail, name="record_detail"),
    path(
        "panel/ewidencja/<uuid:uuid>/przedluz/",
        v.reservation_extend,
        name="reservation_extend",
    ),
    path("panel/eksport/", v.export_records, name="export_records"),
    path("panel/import/", import_records, name="import_records"),
    path("panel/import/pule/", import_pools, name="import_pools"),
    path("panel/pule/", v.pools_list, name="pools_list"),
    path("panel/pule/nowa/", v.pool_new, name="pool_new"),
    path("panel/pule/<uuid:uuid>/", v.pool_detail, name="pool_detail"),
    path("panel/pisma/", v.letters_list, name="letters_list"),
    path("panel/pisma/<uuid:uuid>/pdf/", v.letter_pdf, name="letter_pdf"),
    path("panel/pisma/<uuid:uuid>/podpis/", v.letter_sign, name="letter_sign"),
    path("panel/pisma/<uuid:uuid>/wersja/", v.letter_revision, name="letter_revision"),
    path("panel/pisma/<uuid:uuid>/wyslij/", v.letter_send, name="letter_send"),
    path("panel/pisma/<uuid:uuid>/ezd/", v.letter_ezd, name="letter_ezd"),
    path("panel/audyt/", v.audit_list, name="audit_list"),
    path("panel/integracje/", v.integrations, name="integrations"),
    path("panel/integracje/ezd/wplywy/", v.ezd_incoming, name="ezd_incoming"),
    path(
        "panel/integracje/ezd/wplywy/<uuid:uuid>/link/", v.ezd_incoming_publish, name="ezd_incoming_publish"
    ),
    path("panel/integracje/ezd/wplywy/<uuid:uuid>/pdf/", v.ezd_incoming_pdf, name="ezd_incoming_pdf"),
    path("panel/integracje/adresy/", v.edor_search, name="edor_search"),
    path("panel/integracje/edor/<uuid:uuid>/wznow/", v.edor_resume, name="edor_resume"),
    path("panel/pisma/<uuid:uuid>/dowody/<int:evidence_pk>/", v.delivery_evidence, name="delivery_evidence"),
    path("panel/administracja/", v.admin_panel, name="admin_panel"),
    path(
        "panel/administracja/konta/<int:user_pk>/zaproszenia/",
        account_invitation_views.account_invitations,
        name="account_invitations",
    ),
    path(
        "panel/administracja/konta/<int:user_pk>/zaproszenia/<uuid:uuid>/",
        account_invitation_views.account_invitations,
        name="account_invitation_manage",
    ),
    path("panel/administracja/<str:kind>/nowy/", v.admin_edit, name="admin_new"),
    path("panel/administracja/<str:kind>/<str:pk>/", v.admin_edit, name="admin_edit"),
    path("api/health/", v.health, name="health"),
    path("api/session/", session_views.session_status, name="session_status"),
    path("api/session/extend/", session_views.session_extend, name="session_extend"),
    path("api/availability/", v.api_availability),
    path("api/public-challenge/", v.public_challenge, name="public_challenge"),
    path("api/requests/", v.api_requests),
    path("api/requests/<uuid:uuid>/<str:action>/", v.api_request_action),
    path("api/records/<uuid:uuid>/", v.api_record),
    path("api/pools/", v.api_pools),
    path("api/pools/<uuid:uuid>/issue/", v.api_slot),
]
