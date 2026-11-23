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


class AsciiDigitsMixin:
    """BUG-895 : les champs numériques listés dans `ascii_digit_fields` refusent
    les chiffres non ASCII (« ٣ », « １２ ») envoyés en chaîne (400 en français).

    BUG-897 : si `ascii_digit_fields` vaut `'__numeric__'`, tous les champs
    décimaux / entiers / flottants inscriptibles du serializer sont contrôlés."""
    ascii_digit_fields = ()

    def _ascii_fields(self):
        if self.ascii_digit_fields == '__numeric__':
            from rest_framework import serializers as s
            numeric = (s.DecimalField, s.IntegerField, s.FloatField)
            return [n for n, f in self.fields.items()
                    if isinstance(f, numeric) and not f.read_only]
        return self.ascii_digit_fields

    def to_internal_value(self, data):
        from rest_framework.exceptions import ValidationError
        if hasattr(data, 'get'):
            for name in self._ascii_fields():
                raw = data.get(name)
                if isinstance(raw, str) and not raw.isascii():
                    raise ValidationError({name: ["Valeur invalide (chiffres 0-9 uniquement)."]})
        return super().to_internal_value(data)
