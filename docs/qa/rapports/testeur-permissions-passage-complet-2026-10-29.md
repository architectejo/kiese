# Rapport — testeur-permissions — passage de non-régression complet (2026-10-29)

## Portée
Vérification ciblée sur les changements récents : BUG-082 (CORS desktop), BUG-083/086
(`Config.allow_backdated_sales`), isolation inter-nœuds, migrations.

## 1. `python manage.py test core`
- Résultat : **57/57 OK** (aucun échec, aucune erreur). Durée ~530 s.
- Avertissements drf-spectacular (schéma OpenAPI) uniquement — sans rapport avec les
  permissions, non bloquants.
- Conforme à la demande (hors BUG-068/084/057, qui ne concernent pas l'app `core` de toute
  façon — ils sont dans `treasury`).

## 2. `Config.allow_backdated_sales` — permissions d'écriture/lecture
Vérifié par lecture directe du code (`backend/core/views.py::ConfigView.get_permissions`) :
GET → `AllowAny`, tout le reste (PUT/PATCH) → `IsDirection()` (ADMIN/DIRECTION uniquement).
Ce n'est pas un contrôle par champ mais par verbe HTTP sur toute la ressource `Config` —
donc `allow_backdated_sales` hérite de la même règle que les autres réglages globaux
(`best_client_threshold`, etc.). Confirmé par les tests existants
`backend/core/tests/test_bug083_config_backdated_sales.py` :
- `test_gerant_cannot_enable_it` / `test_facturier_cannot_enable_it` → 403, valeur inchangée.
- `test_admin_can_enable_it` / `test_direction_can_enable_it` → 200, appliqué.
- `test_facturier_can_read_the_flag` → GET autorisé pour FACTURIER une fois le réglage actif
  (nécessaire pour afficher le champ de date côté Clients.tsx/Sales.tsx), confirmant que seule
  l'écriture est restreinte, pas la lecture. Conforme à la décision client citée dans le test.

Un FACTURIER ne peut donc ni activer/désactiver le réglage, ni accéder via ce nouveau champ à
une fonctionnalité qui lui serait normalement interdite : `sales/views.py::InvoiceViewSet`
applique la validation de date (`_validate_requested_date`, qui lit `Config.allow_backdated_sales`)
à l'intérieur du même chemin `create()`/`deliver()` déjà protégé par `IsFacturierOrLivreur`/
`IsFacturier` — aucune route ni verbe supplémentaire n'est ouvert par ce champ.

## 3. `backend/kiese/settings.py` (cloud) — relu intégralement, section CORS
```
CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS',
    'http://localhost:5173,http://127.0.0.1:5173,https://etskiese.com,https://www.etskiese.com'
).split(',')
CORS_ALLOW_CREDENTIALS = True
```
Confirmé non modifié par BUG-082 : pas de `CORS_ALLOW_ALL_ORIGINS`, pas d'origine `null`,
pas de regex ajoutée. Les changements BUG-082 (`CORS_ALLOWED_ORIGINS = ['null']` +
`CORS_ALLOWED_ORIGIN_REGEXES` ancrée sur `127.0.0.1`) sont bien confinés à
`backend/kiese/settings_desktop.py` (lignes 77-120), fichier séparé utilisé uniquement en
mode poste desktop. Le serveur cloud (settings.py) reste sur une liste blanche statique.

## 4. Isolation inter-nœuds (y compris avec les nouveaux champs de date)
`sales/views.py::InvoiceViewSet._create_once` (ligne ~246-250) :
```python
if not request.user.can_access_all_nodes:
    node_id = getattr(request.user, 'node_id', None)   # ignore toute valeur `node` du corps
else:
    node_id = data.get('node') or getattr(request.user, 'node_id', None)
```
Ce verrou (BUG-030, préexistant) s'applique à **tout** `create()`, qu'il y ait ou non une
date rétroactive dans le payload — le champ `invoice_date` n'a aucun chemin de code séparé qui
contournerait cette ligne. Un FACTURIER/GERANT non-HQ ne peut donc toujours pas créer, même
avec `allow_backdated_sales=True`, une facture pour un autre nœud que le sien : le `node` fourni
dans le corps est simplement ignoré, pas seulement rejeté. `get_queryset()` filtre également par
`node=user.node` pour la lecture (liste/détail), inchangé par BUG-083/086.
`backend/core/permissions.py::NodeScopedPermission` reste la base pour les autres apps, non
touchée. Conclusion : **aucune régression d'isolation détectée**, y compris autour des nouveaux
champs de date.

## 5. Test manuel en navigateur
Un serveur backend (port 8000) et un serveur frontend Vite (port 5173) étaient déjà actifs sur
la machine au moment de ce passage (processus `python.exe`/`node.exe` trouvés, et réponses HTTP
200 obtenues sur `/api/core/config/` et `/`). Faute d'outil de navigateur dans mon panel d'outils
pour cette session, je n'ai pas pu produire de capture console navigateur par rôle — je n'ai fait
que des vérifications read-only en base (lecture de la liste des comptes de démonstration
`demo_*_e2e`, aucune écriture). **Ce point (item 5 de la mission) n'est donc pas pleinement
couvert par ce passage** : à reprendre par un agent disposant d'un outil Playwright/navigateur,
ou en confirmant d'abord qu'aucun autre agent n'utilise les serveurs en cours avant de les
redémarrer avec des comptes `DEMO`/`TEST` dédiés.

## 6. Migrations
`python manage.py showmigrations` sur la vraie base : **0 migration en attente** (toutes `[X]`),
y compris `core/0015_config_allow_backdated_sales`. Base non modifiée pendant ce passage (aucune
commande `migrate`/`shell` exécutée en écriture).

## Anomalies trouvées
**Aucune anomalie de sécurité nouvelle.** Les contrôles vérifiés (RBAC sur `Config`, isolation
de nœud sur la création de factures y compris rétroactives, CORS cloud vs desktop, migrations)
sont tous conformes. Le seul ticket ouvert dans le périmètre proche est **BUG-085** (hash du
livre de caisse ne couvre pas `is_correction`), déjà consigné, Mineur, non bloquant, et déjà
signalé par `testeur-tresorerie` — je ne le réouvre pas en double.

## Verdict
**Module Permissions/Sécurité : prêt pour le volet backend testé** (RBAC sur `Config`,
isolation de nœud, CORS cloud, migrations — tous conformes, 57/57 tests `core` au vert).
**Réserve non négligeable avant présentation client** : le test manuel multi-rôles en
navigateur (item 5 de la mission) n'a pas pu être exécuté par cet agent faute d'outil
navigateur disponible dans cette session ; je recommande qu'un agent équipé d'un outil
Playwright/navigateur (ex. `testeur-e2e`) confirme l'absence d'erreur console avant la
démonstration finale. Sous cette réserve explicite, aucun blocage connu ne subsiste côté
permissions/isolation.
