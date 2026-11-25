"""
Fabriques de données fictives partagées entre les suites de tests de tous
les modules (CLAUDE.md §7 règle 1 : « backend/core/testing.py »).

Aucune de ces fabriques n'écrit de données réelles de l'ETS. KIESE — tout
est fictif (ex. ERREUR si on importe `data_kiese/`, interdit par CLAUDE.md §4).
"""
from decimal import Decimal

from core.models import Node, User, BreadPrice, Config
from clients.models import Client

_node_seq = [0]
_client_seq = [0]
_user_seq = [0]


def make_node(code=None, name=None, sac_value_fc=None,
              social=Decimal('0.00'), card_fee=Decimal('0.00'), rotation=False):
    # BUG-417 : les defauts reels d'une nouvelle boulangerie sont 2000 / 1000 FC
    # (Node.monthly_social_contribution / card_fee_fc). Les fabriques de test
    # restent neutres (0) pour que les scenarios existants calculent a la main
    # sans retenue implicite ; les tests de defauts creent le Node directement.
    _node_seq[0] += 1
    code = code or f"TK{_node_seq[0]}"
    name = name or f"Boulangerie Test {code}"
    # Q-017 (2026-11-24) : en production `Node.team_rotation_enabled` vaut True par defaut.
    # La fabrique reste neutre (rotation=False) pour ne pas changer les scenarios historiques
    # (hors rotation) ; les tests de rotation passent rotation=True ou activent le drapeau.
    return Node.objects.create(code=code, name=name, sac_value_fc=sac_value_fc,
                               monthly_social_contribution=social, card_fee_fc=card_fee,
                               team_rotation_enabled=rotation)


def make_user(role='FACTURIER', node=None, team='A', username=None, password='test-pass-123'):
    _user_seq[0] += 1
    username = username or f"test_{role.lower()}_{_user_seq[0]}"
    user = User.objects.create_user(
        username=username, password=password,
        role=role, node=node, team=team,
    )
    return user


def make_bread_price(category='MOYEN', label='Pain Test 500 FC', unit_price=500, is_active=True):
    bp, _ = BreadPrice.objects.get_or_create(
        category=category,
        defaults={'label': label, 'unit_price': unit_price, 'is_active': is_active},
    )
    if bp.unit_price != unit_price:
        bp.unit_price = unit_price
        bp.label = label
        bp.is_active = is_active
        bp.save()
    return bp


def make_client(node, credit_limit=Decimal('50000.00'), current_debt=Decimal('0.00'),
                 commission_rate=Decimal('0.25'), first_name=None, last_name='Testeur'):
    _client_seq[0] += 1
    first_name = first_name or f"Client{_client_seq[0]}"
    return Client.objects.create(
        node=node, node_origin=node.code,
        first_name=first_name, last_name=last_name,
        credit_limit=credit_limit, current_debt=current_debt,
        commission_rate=commission_rate,
    )


def get_config():
    return Config.get_instance()
