"""Mixins DRF communs."""


MAX_NODE_ID = 2_147_483_647


def parse_node_param(raw, name='node'):
    """BUG-532 / BUG-530 : convertit un paramètre `?node=` en entier borné.

    Lève ValidationError (400, `{"detail": ...}` en français) si la valeur n'est
    pas un entier positif tenant dans un INTEGER SQLite/PostgreSQL."""
    from rest_framework.exceptions import ValidationError
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        value = None
    if value is None or value < 1 or value > MAX_NODE_ID:
        raise ValidationError(
            {'detail': f"Paramètre « {name} » invalide : identifiant de boulangerie numérique attendu."})
    return value


def is_node_less_non_hq(user):
    """BUG-506 : vrai pour un compte lié à une boulangerie (GERANT/FACTURIER/LIVREUR)
    sans nœud : il ne doit voir aucune donnée (et non toutes)."""
    return not user.can_access_all_nodes and not user.node_id


class NodeImmutableForNonHQMixin:
    """BUG-313 : un utilisateur rattaché à une boulangerie (non siège) ne peut
    jamais déplacer une ligne existante vers une autre boulangerie.

    En PUT/PATCH, le champ `node` du serializer est rendu en lecture seule pour
    tout utilisateur qui n'a pas `can_access_all_nodes` : la valeur envoyée est
    ignorée silencieusement (même politique que BUG-025 / BUG-056 / perform_create
    BUG-022). Sans effet si le serializer n'expose pas `node`.
    """

    def get_serializer(self, *args, **kwargs):
        serializer = super().get_serializer(*args, **kwargs)
        user = getattr(self.request, 'user', None)
        if (getattr(self, 'action', None) in ('update', 'partial_update')
                and user is not None and user.is_authenticated
                and not user.can_access_all_nodes):
            field = serializer.fields.get('node')
            if field is not None:
                field.read_only = True
                field.required = False
        return serializer


def get_json_object(request):
    """BUG-762 : renvoie `request.data` si le corps est un objet JSON (ou un
    formulaire) ; sinon (liste, nombre, chaîne, null) lève une 400 en français
    au lieu d'un 500 sur `.get(...)`."""
    from rest_framework.exceptions import ValidationError
    data = request.data
    if isinstance(data, dict):  # inclut QueryDict
        return data
    raise ValidationError({'detail': "Corps de requête invalide : un objet JSON est attendu."})
