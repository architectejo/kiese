"""Mixins DRF communs."""


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
