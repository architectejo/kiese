"""
Fonction de hash unique du Livre de Caisse Direction (CashbookEntry).

BUG-001 (registre QA) : avant cette correction, `treasury/views.py` et
`blockchain/views.py` calculaient chacun leur propre hash avec des formules
différentes (JSON trié avec previous_hash d'un côté, concaténation f-string
de l'autre), si bien que toute écriture — même parfaitement saine — était
signalée comme falsifiée dès qu'on la revérifiait depuis `blockchain`.

Ce module est l'UNIQUE endroit où la formule de hash est définie. Il est
importé à la fois par `treasury` (à l'écriture, dans `push_to_cashbook` et
dans la création de `DisbursementVoucher`) et par `blockchain` (à la
vérification, dans `_verify_chain_for_node` / `integrity_check`).

BUG-003 : le hash couvre désormais tous les champs comptables sensibles,
y compris `node`, `imputation`, `source_closure` et `source_bordereau`
(ce dernier n'était pas explicitement demandé par le ticket mais couvre la
même catégorie de risque qu'un `source_closure` falsifié — une sortie de
caisse Direction pourrait sinon être réattribuée à un autre bordereau sans
casser la chaîne).

BUG-085 : BUG-083 a ajouté 4 champs de traçabilité des corrections
rétroactives à `CashbookEntry` (`is_correction`, `correction_reason`,
`corrected_by`, `correction_source_invoice`), mais aucun n'entrait dans la
formule de hash. `correction_reason`/`corrected_by`/`correction_source_invoice`
restent hors formule (texte d'audit libre, même statut que `node_origin`/
`created_at`). `is_correction` est différent : c'est une classification
comptable binaire (« ceci est une correction, pas un mouvement d'origine »)
que CLAUDE.md §5.5 veut protéger contre toute altération silencieuse —
exactement ce que le chaînage doit détecter. Il entre désormais dans le
payload (voir migration `0014_bug085_recompute_hash_is_correction`).

Volontairement, ce module ne dépend d'aucun modèle Django au niveau du
module (seulement des attributs dynamiques de l'objet `entry` qu'on lui
passe) : cela évite tout risque d'import circulaire entre `treasury` et
`blockchain`.
"""
import hashlib
import json
from decimal import Decimal, InvalidOperation

# Incrémenter si la formule change à nouveau (utile pour documenter/auditer
# quelle version a produit un `block_hash` donné — voir migrations
# 0007_recompute_cashbook_hash (v1 -> v2) et
# 0014_bug085_recompute_hash_is_correction (v2 -> v3).
HASH_FORMAT_VERSION = 3


def _normalize_amount(value) -> str:
    """Convertit un montant Decimal/str/None en chaîne canonique à 2 décimales.

    Évite que 'running_balance=Decimal(\"0\")' et 'running_balance=Decimal(\"0.00\")'
    produisent deux hash différents pour la même valeur réelle.
    """
    if value is None:
        return '0.00'
    try:
        d = Decimal(value)
    except (InvalidOperation, TypeError):
        d = Decimal('0')
    return str(d.quantize(Decimal('0.01')))


def _normalize_date(value) -> str:
    if value is None:
        return ''
    # date/datetime exposent isoformat(); une chaîne est déjà canonique.
    isoformat = getattr(value, 'isoformat', None)
    return isoformat() if callable(isoformat) else str(value)


def compute_cashbook_entry_hash(entry, previous_hash=None) -> str:
    """Calcule le hash SHA-256 canonique d'une écriture du Livre de Caisse.

    :param entry: une instance de `treasury.models.CashbookEntry` (ou tout
        objet exposant les mêmes attributs — utilisé aussi pendant la
        migration de données sur des lignes brutes via un modèle historique).
    :param previous_hash: hash du bloc précédent à utiliser dans le calcul.
        Si ``None``, on utilise ``entry.previous_hash`` tel que stocké
        (c'est le cas normal à l'écriture). La vérification de chaîne
        (`blockchain`) passe explicitement le hash attendu du bloc
        précédent — reconstruit pendant le parcours — plutôt que de faire
        confiance à la valeur stockée dans l'entrée elle-même, afin de
        pouvoir détecter une falsification de `previous_hash` en plus
        d'une falsification des autres champs.
    """
    if previous_hash is None:
        previous_hash = entry.previous_hash or ''

    payload = {
        'id': str(entry.id),
        'node': str(entry.node_id) if getattr(entry, 'node_id', None) else '',
        'date': _normalize_date(entry.date),
        'piece_number': entry.piece_number or '',
        'imputation': entry.imputation or '',
        'label': entry.label or '',
        'entry_amount': _normalize_amount(entry.entry_amount),
        'exit_amount': _normalize_amount(entry.exit_amount),
        'running_balance': _normalize_amount(entry.running_balance),
        'source_closure': str(entry.source_closure_id) if getattr(entry, 'source_closure_id', None) else '',
        'source_bordereau': str(entry.source_bordereau_id) if getattr(entry, 'source_bordereau_id', None) else '',
        # BUG-085 : classification comptable binaire à protéger (voir
        # docstring du module) — booléen normalisé explicitement pour éviter
        # toute ambiguïté de sérialisation JSON entre `True`/`'True'`/`1`.
        'is_correction': bool(getattr(entry, 'is_correction', False)),
        'previous_hash': previous_hash or '',
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def compute_v2_hash(entry, previous_hash=None) -> str:
    """Reproduit la formule v2 (BUG-001/BUG-003), AVANT l'ajout de
    `is_correction` par BUG-085 — c'est la formule qui a réellement servi à
    écrire les `block_hash` en base entre la migration `0007` et la
    migration `0014_bug085_recompute_hash_is_correction`.

    Utilisée uniquement par cette dernière migration, sur le même principe
    que `compute_legacy_v1_hash` pour la migration `0007` : (1) vérifier que
    les écritures existantes n'étaient pas déjà falsifiées sous l'ancienne
    formule avant de leur appliquer la nouvelle, et (2) permettre à la
    migration inverse de revenir exactement à l'état précédent.
    Ne pas utiliser ailleurs.
    """
    if previous_hash is None:
        previous_hash = entry.previous_hash or ''
    payload = {
        'id': str(entry.id),
        'node': str(entry.node_id) if getattr(entry, 'node_id', None) else '',
        'date': _normalize_date(entry.date),
        'piece_number': entry.piece_number or '',
        'imputation': entry.imputation or '',
        'label': entry.label or '',
        'entry_amount': _normalize_amount(entry.entry_amount),
        'exit_amount': _normalize_amount(entry.exit_amount),
        'running_balance': _normalize_amount(entry.running_balance),
        'source_closure': str(entry.source_closure_id) if getattr(entry, 'source_closure_id', None) else '',
        'source_bordereau': str(entry.source_bordereau_id) if getattr(entry, 'source_bordereau_id', None) else '',
        'previous_hash': previous_hash or '',
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def compute_legacy_v1_hash(entry, previous_hash=None) -> str:
    """Reproduit l'ANCIENNE formule de `treasury/views.py::_compute_hash`
    (celle qui a réellement servi à écrire les `block_hash` déjà en base
    avant cette correction — `blockchain/views.py` avait sa propre formule
    de concaténation, mais elle n'était utilisée qu'en vérification, jamais
    à l'écriture, donc ce n'est pas la référence pertinente pour auditer les
    données existantes).

    Utilisée uniquement par la migration de données `0007_recompute_cashbook_hash`
    pour (1) vérifier que les écritures existantes n'étaient pas déjà
    falsifiées avant de leur appliquer la nouvelle formule, et (2) permettre
    à la migration inverse de revenir exactement à l'état précédent.
    Ne pas utiliser ailleurs.
    """
    if previous_hash is None:
        previous_hash = entry.previous_hash or ''
    payload = json.dumps({
        'id': str(entry.id),
        'date': str(entry.date),
        'piece_number': entry.piece_number,
        'label': entry.label,
        'entry_amount': str(entry.entry_amount),
        'exit_amount': str(entry.exit_amount),
        'running_balance': str(entry.running_balance),
        'previous_hash': previous_hash,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


GENESIS_HASH = '0' * 64


def verify_cashbook_chain(entries):
    """Parcourt une suite ordonnée par rang de chaînage (`chain_seq`, BUG-199) de `CashbookEntry` et
    recalcule le hash attendu de chacune avec la formule canonique.

    Fonction UNIQUE de vérification, utilisée à la fois par
    `treasury.views.CashbookEntryViewSet.integrity_check` et par
    `blockchain.views._verify_chain_for_node` (BUG-001) : avant cette
    correction, les deux endpoints réimplémentaient chacun leur propre
    boucle de vérification, en plus d'utiliser des formules de hash
    différentes.

    Ne fait pas confiance à `entry.previous_hash` tel que stocké : reconstruit
    le hash précédent attendu au fil du parcours, en ne l'avançant que si le
    bloc courant est valide. Ainsi, après une première falsification, les
    blocs suivants continuent d'être comparés à la dernière valeur connue du
    chaînage et toute rupture supplémentaire est également signalée (et pas
    seulement la première).

    Retourne une liste de tuples ``(entry, expected_hash, is_valid)``.
    """
    results = []
    previous_hash = GENESIS_HASH
    for entry in entries:
        expected = compute_cashbook_entry_hash(entry, previous_hash=previous_hash)
        is_valid = (entry.block_hash == expected)
        results.append((entry, expected, is_valid))
        if is_valid:
            previous_hash = entry.block_hash
    return results
