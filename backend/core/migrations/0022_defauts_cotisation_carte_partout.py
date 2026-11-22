"""BUG-417 (decision du responsable, 2026-11-22) : cotisation sociale = 2 000 FC et
carte = 1 000 FC pour TOUTES les boulangeries, existantes comme nouvelles.

Migration de donnees uniquement (le schema et les defauts du modele sont deja
poses par 0021, deja poussee : non modifiee).

- valeur 0 -> valeur par defaut ;
- valeur strictement positive differente (ex. 3000) : NON ecrasee, signalee ;
- idempotente (un second passage ne change rien) ;
- reverse : no-op documente (impossible de distinguer un 2000/1000 pose par
  cette migration d'une valeur saisie a la main ; les commissions deja generees
  ne sont de toute facon jamais touchees).
"""
import logging
from decimal import Decimal

from django.db import migrations

logger = logging.getLogger(__name__)

SOCIAL_DEFAULT = Decimal('2000.00')
CARD_DEFAULT = Decimal('1000.00')


def apply_defaults(apps, schema_editor):
    """Retourne la liste des valeurs propres conservees [(code, champ, valeur)]."""
    Node = apps.get_model('core', 'Node')
    kept = []
    for node in Node.objects.all():
        changed = []
        for field, default in (('monthly_social_contribution', SOCIAL_DEFAULT),
                               ('card_fee_fc', CARD_DEFAULT)):
            value = getattr(node, field)
            if value is None or value == 0:
                setattr(node, field, default)
                changed.append(field)
            elif value != default:
                kept.append((node.code, field, value))
        if changed:
            node.save(update_fields=changed)
    for code, field, value in kept:
        msg = f"BUG-417 : {code}.{field} = {value} conserve (valeur propre, non ecrasee)"
        logger.warning(msg)
        print(msg)
    return kept


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_node_card_fee_fc'),
    ]

    operations = [
        migrations.RunPython(apply_defaults, migrations.RunPython.noop),
    ]
