# BUG-001 / BUG-003 (docs/qa/REGISTRE_BUGS.md) : unification de la formule de
# hash du Livre de Caisse Direction.
#
# Avant cette migration, `treasury/views.py::_compute_hash` (JSON trié,
# previous_hash inclus) et `blockchain/views.py::_verify_chain_for_node`
# (concaténation f-string) utilisaient deux formules différentes — seule la
# première a jamais été utilisée pour ÉCRIRE un `block_hash` (la seconde ne
# servait qu'à la vérification, jamais à l'écriture). Cette migration
# recalcule donc chaque `block_hash`/`previous_hash` avec la nouvelle
# formule unique (`treasury.hashing.compute_cashbook_entry_hash`), qui
# couvre en plus `node`, `imputation`, `source_closure` et
# `source_bordereau` (BUG-003).
#
# Choix assumé (à documenter dans le rapport de l'agent plutôt qu'à trancher
# silencieusement) : on NE recalcule PAS à l'aveugle. On vérifie d'abord la
# chaîne existante avec l'ANCIENNE formule (celle qui a réellement servi à
# l'écriture — `compute_legacy_v1_hash`). Tant que cette vérification est
# positive, l'écriture n'était pas déjà falsifiée sous l'ancienne règle : on
# peut recalculer en toute sécurité son nouveau hash. Dès la première
# rupture détectée sous l'ancienne formule, on arrête le recalcul : cette
# écriture et toutes les suivantes restent "hash legacy" (ancienne formule,
# volontairement non modifiées) plutôt que d'écraser silencieusement une
# preuve de falsification réelle. Un contrôle d'intégrité
# (`/api/blockchain/snapshots/run_check/`) lancé après cette migration les
# détectera explicitement comme falsifiées.
#
# Réversible : `revert_to_legacy_hash` ne restaure que le préfixe que cette
# migration a effectivement modifié (déterminé en revérifiant quelles
# écritures valident sous la NOUVELLE formule depuis le génésis), laissant
# intact tout ce qui était déjà "legacy" avant la migration.
from django.db import migrations


def recompute_new_hash(apps, schema_editor):
    CashbookEntry = apps.get_model('treasury', 'CashbookEntry')
    from treasury.hashing import compute_cashbook_entry_hash, compute_legacy_v1_hash, GENESIS_HASH

    entries = list(CashbookEntry.objects.order_by('date', 'created_at'))
    if not entries:
        return

    # Passe 1 : vérifier la chaîne existante sous l'ANCIENNE formule — celle
    # qui a réellement produit les block_hash en base avant cette migration.
    previous_hash_old = GENESIS_HASH
    chain_broken_at = None
    for entry in entries:
        expected_old = compute_legacy_v1_hash(entry, previous_hash=previous_hash_old)
        if entry.block_hash != expected_old:
            chain_broken_at = entry.pk
            break
        previous_hash_old = entry.block_hash

    # Passe 2 : recalculer avec la NOUVELLE formule uniquement le préfixe
    # validé ci-dessus. Le reste (à partir de chain_broken_at) n'est pas
    # touché : il reste "hash legacy, non vérifiable rétroactivement".
    previous_hash_new = GENESIS_HASH
    recomputed = 0
    for entry in entries:
        if chain_broken_at is not None and entry.pk == chain_broken_at:
            break
        entry.previous_hash = previous_hash_new
        entry.block_hash = compute_cashbook_entry_hash(entry, previous_hash=previous_hash_new)
        entry.save(update_fields=['previous_hash', 'block_hash'])
        previous_hash_new = entry.block_hash
        recomputed += 1

    if chain_broken_at is not None:
        print(
            f"[0007_recompute_cashbook_hash] {recomputed} écriture(s) recalculée(s) avec la "
            f"nouvelle formule. ATTENTION : rupture détectée sous l'ancienne formule a "
            f"l'écriture pk={chain_broken_at} — cette écriture et toutes les suivantes "
            f"n'ont PAS été recalculées (hash legacy, non vérifiable rétroactivement). "
            f"Lancez un contrôle d'intégrité blockchain après la migration pour les "
            f"identifier précisément et ouvrir une TamperAlert si nécessaire."
        )
    else:
        print(f"[0007_recompute_cashbook_hash] {recomputed} écriture(s) recalculée(s) avec la nouvelle formule, aucune rupture détectée.")


def revert_to_legacy_hash(apps, schema_editor):
    CashbookEntry = apps.get_model('treasury', 'CashbookEntry')
    from treasury.hashing import compute_cashbook_entry_hash, compute_legacy_v1_hash, GENESIS_HASH

    entries = list(CashbookEntry.objects.order_by('date', 'created_at'))
    if not entries:
        return

    # Redétermine la frontière du préfixe effectivement touché par la
    # migration forward : il valide sous la NOUVELLE formule depuis le
    # génésis ; le reste (legacy, jamais touché) ne valide pas.
    touched_count = 0
    previous_hash_new = GENESIS_HASH
    for entry in entries:
        expected_new = compute_cashbook_entry_hash(entry, previous_hash=previous_hash_new)
        if entry.block_hash != expected_new:
            break
        touched_count += 1
        previous_hash_new = entry.block_hash

    previous_hash_old = GENESIS_HASH
    for entry in entries[:touched_count]:
        entry.previous_hash = previous_hash_old
        entry.block_hash = compute_legacy_v1_hash(entry, previous_hash=previous_hash_old)
        entry.save(update_fields=['previous_hash', 'block_hash'])
        previous_hash_old = entry.block_hash

    print(f"[0007_recompute_cashbook_hash] reverse : {touched_count} écriture(s) restaurée(s) à l'ancienne formule.")


class Migration(migrations.Migration):

    dependencies = [
        ('treasury', '0006_disbursement_voucher'),
    ]

    operations = [
        migrations.RunPython(recompute_new_hash, revert_to_legacy_hash),
    ]
