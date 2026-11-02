# BUG-085 (docs/qa/REGISTRE_BUGS.md) : `compute_cashbook_entry_hash` couvre
# désormais `is_correction` (en plus de `node`/`imputation`/`source_closure`/
# `source_bordereau` déjà couverts depuis BUG-003). Avant cette migration, une
# falsification directe en base de ce seul champ (ex.
# `CashbookEntry.objects.filter(pk=x).update(is_correction=False)`) ne cassait
# pas la chaîne de hash puisque le champ n'entrait pas dans le calcul.
#
# Même schéma que `0007_recompute_cashbook_hash` (BUG-001/BUG-003) : on NE
# recalcule PAS à l'aveugle. On vérifie d'abord la chaîne existante avec la
# formule v2 (`compute_v2_hash`, celle qui a réellement servi à écrire les
# `block_hash` jusqu'ici). Tant que cette vérification est positive,
# l'écriture n'était pas déjà falsifiée sous la formule v2 : on peut
# recalculer en toute sécurité son nouveau hash v3. Dès la première rupture
# détectée sous la formule v2, on arrête le recalcul : cette écriture et
# toutes les suivantes restent "hash v2" (non modifiées) plutôt que d'écraser
# silencieusement une preuve de falsification réelle déjà présente.
#
# `is_correction` vaut `False` par défaut pour toute écriture antérieure à
# BUG-083 (champ ajouté par la migration 0011 avec `default=False`, jamais
# modifié par du code applicatif en dehors du mécanisme de correction
# rétroactive). Pour ces écritures, `bool(False)` dans le nouveau payload v3
# est la même valeur implicite qu'avant (le champ n'existait simplement pas
# dans le payload v2) : le recalcul ne change donc RIEN pour elles — seul le
# hash des écritures où `is_correction=True` change réellement de valeur.
# Vérifié explicitement dans le rapport de l'agent (comptage par
# `is_correction`), pas seulement affirmé ici.
#
# Réversible : `revert_to_v2_hash` ne restaure que le préfixe que cette
# migration a effectivement modifié (déterminé en revérifiant quelles
# écritures valident sous la formule v3 depuis le génésis), laissant intact
# tout ce qui était déjà "v2 legacy" avant la migration.
from django.db import migrations


def recompute_v3_hash(apps, schema_editor):
    CashbookEntry = apps.get_model('treasury', 'CashbookEntry')
    from treasury.hashing import compute_cashbook_entry_hash, compute_v2_hash, GENESIS_HASH

    entries = list(CashbookEntry.objects.order_by('date', 'created_at'))
    if not entries:
        return

    # Passe 1 : vérifier la chaîne existante sous la formule v2 — celle qui a
    # réellement produit les block_hash en base avant cette migration.
    previous_hash_v2 = GENESIS_HASH
    chain_broken_at = None
    for entry in entries:
        expected_v2 = compute_v2_hash(entry, previous_hash=previous_hash_v2)
        if entry.block_hash != expected_v2:
            chain_broken_at = entry.pk
            break
        previous_hash_v2 = entry.block_hash

    # Passe 2 : recalculer avec la formule v3 (is_correction inclus)
    # uniquement le préfixe validé ci-dessus.
    previous_hash_v3 = GENESIS_HASH
    recomputed = 0
    changed = 0
    for entry in entries:
        if chain_broken_at is not None and entry.pk == chain_broken_at:
            break
        old_hash = entry.block_hash
        entry.previous_hash = previous_hash_v3
        entry.block_hash = compute_cashbook_entry_hash(entry, previous_hash=previous_hash_v3)
        entry.save(update_fields=['previous_hash', 'block_hash'])
        if entry.block_hash != old_hash:
            changed += 1
        previous_hash_v3 = entry.block_hash
        recomputed += 1

    if chain_broken_at is not None:
        print(
            f"[0014_bug085_recompute_hash_is_correction] {recomputed} écriture(s) recalculée(s) "
            f"avec la formule v3 ({changed} effectivement modifiée(s), is_correction=True). "
            f"ATTENTION : rupture détectée sous la formule v2 a l'écriture pk={chain_broken_at} "
            f"— cette écriture et toutes les suivantes n'ont PAS été recalculées (hash v2 legacy, "
            f"non vérifiable rétroactivement). Lancez un contrôle d'intégrité blockchain après la "
            f"migration pour les identifier précisément et ouvrir une TamperAlert si nécessaire."
        )
    else:
        print(
            f"[0014_bug085_recompute_hash_is_correction] {recomputed} écriture(s) recalculée(s) "
            f"avec la formule v3, {changed} effectivement modifiée(s) (is_correction=True), "
            f"aucune rupture détectée sous la formule v2."
        )


def revert_to_v2_hash(apps, schema_editor):
    CashbookEntry = apps.get_model('treasury', 'CashbookEntry')
    from treasury.hashing import compute_cashbook_entry_hash, compute_v2_hash, GENESIS_HASH

    entries = list(CashbookEntry.objects.order_by('date', 'created_at'))
    if not entries:
        return

    # Redétermine la frontière du préfixe effectivement touché par la
    # migration forward : il valide sous la formule v3 depuis le génésis ;
    # le reste (v2 legacy, jamais touché) ne valide pas.
    touched_count = 0
    previous_hash_v3 = GENESIS_HASH
    for entry in entries:
        expected_v3 = compute_cashbook_entry_hash(entry, previous_hash=previous_hash_v3)
        if entry.block_hash != expected_v3:
            break
        touched_count += 1
        previous_hash_v3 = entry.block_hash

    previous_hash_v2 = GENESIS_HASH
    for entry in entries[:touched_count]:
        entry.previous_hash = previous_hash_v2
        entry.block_hash = compute_v2_hash(entry, previous_hash=previous_hash_v2)
        entry.save(update_fields=['previous_hash', 'block_hash'])
        previous_hash_v2 = entry.block_hash

    print(f"[0014_bug085_recompute_hash_is_correction] reverse : {touched_count} écriture(s) restaurée(s) à la formule v2.")


class Migration(migrations.Migration):

    dependencies = [
        ('treasury', '0013_bug057_schema_drift_fix'),
    ]

    operations = [
        migrations.RunPython(recompute_v3_hash, revert_to_v2_hash),
    ]
