"""BUG-228 : répare le double encodage UTF-8 lu en latin-1/cp1252 (« GÃ©rant » -> « Gérant »).

Idempotent. Simulation par défaut ; --apply pour écrire. Un texte déjà correct
(non décodable comme UTF-8 après ré-encodage latin-1/cp1252) n'est jamais modifié.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

# (app_label.Model, champs texte)
TARGETS = [
    ('core.User', ['first_name', 'last_name']),
    ('core.Node', ['name', 'address']),
    ('core.ExpenseCategory', ['label']),
    ('core.BreadPrice', ['label']),
    ('core.ColisDistribution', ['beneficiary_label']),
    ('core.ActivityLog', ['user_display']),
]


def fix_mojibake(value):
    """Retourne le texte réparé, ou `value` inchangé s'il n'est pas du mojibake."""
    if not value or value.isascii():
        return value
    for enc in ('cp1252', 'latin-1'):
        try:
            fixed = value.encode(enc).decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if fixed != value:
            return fixed
    return value


class Command(BaseCommand):
    help = "Répare le double encodage UTF-8/latin-1 des champs texte (BUG-228). Simulation par défaut."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help="Écrit les corrections (sinon simulation).")
        parser.add_argument('--dry-run', action='store_true', help="Simulation (comportement par défaut).")

    def handle(self, *args, **options):
        from django.apps import apps
        apply = options['apply'] and not options['dry_run']
        total = 0
        with transaction.atomic():
            for label, fields in TARGETS:
                model = apps.get_model(label)
                for obj in model.objects.all().iterator():
                    changes = {}
                    for f in fields:
                        old = getattr(obj, f, None)
                        if isinstance(old, str):
                            new = fix_mojibake(old)
                            if new != old:
                                changes[f] = new
                    if not changes:
                        continue
                    total += 1
                    self.stdout.write(f"{label} {obj.pk}: " + ', '.join(
                        f"{f}: {getattr(obj, f)!r} -> {v!r}" for f, v in changes.items()))
                    if apply:
                        # update() : pas de signaux ni de changement de updated_at/is_synced.
                        model.objects.filter(pk=obj.pk).update(**changes)
        mode = 'corrigé(s)' if apply else 'à corriger (simulation, utiliser --apply)'
        self.stdout.write(self.style.SUCCESS(f"{total} enregistrement(s) {mode}."))
