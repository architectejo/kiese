"""Verification BUG-313/314 (testeur-permissions, 2026-11-20).

Pour chaque viewset couvert par NodeImmutableForNonHQMixin : un objet est cree
cote K1 (fabrique generique, donnees fictives), puis
  - gerant K1 : PATCH {node: K2} et PUT (representation GET avec node=K2) -> node inchange,
    aucune erreur 5xx ; l'objet de K2 reste invisible (404) ;
  - gerant K1 : POST avec node=K2 -> objet cree en K1 (ou refus), jamais en K2 ;
  - siege (DIRECTION) : comportement non regresse (PATCH {node: K1} sans 5xx).
"""
import datetime
import uuid
from decimal import Decimal as Dc

from django.db import models as dm, transaction
from django.apps import apps

from core.tests.test_permissions_regression_2026_11_19 import Base, cl

TARGETS = [
    ('clients', 'SocialContribution', '/api/clients/contributions/'),
    ('clients', 'SocialDistribution', '/api/clients/distributions/'),
    ('commissions', 'CommissionPeriod', '/api/commissions/periods/'),
    ('commissions', 'ClientCommission', '/api/commissions/commissions/'),
    ('production', 'ProductionSession', '/api/production/sessions/'),
    ('production', 'ConsumableStock', '/api/production/stocks/'),
    ('production', 'ConsumableMovement', '/api/production/movements/'),
    ('production', 'ConsumableCount', '/api/production/counts/'),
    ('production', 'BreadDisposal', '/api/production/disposals/'),
    ('treasury', 'LocalExpense', '/api/treasury/expenses/'),
    ('treasury', 'FacturierReport', '/api/treasury/reports/'),
    ('treasury', 'CashClosure', '/api/treasury/closures/'),
    ('treasury', 'DisbursementVoucher', '/api/treasury/vouchers/'),
    ('treasury', 'JournalEntry', '/api/treasury/journal/'),
    ('treasury', 'DailySavings', '/api/treasury/savings/'),
    ('core', 'ColisDistribution', '/api/core/colis/'),
]


def _value(field, n):
    if isinstance(field, dm.BooleanField):
        return False
    if isinstance(field, (dm.IntegerField,)):
        return 1
    if isinstance(field, dm.DecimalField):
        return Dc('1')
    if isinstance(field, dm.FloatField):
        return 1.0
    if isinstance(field, dm.DateTimeField):
        return datetime.datetime(2026, 11, 18, 10, 0, tzinfo=datetime.timezone.utc)
    if isinstance(field, dm.DateField):
        return datetime.date(2026, 11, 10 + (n % 15))
    if isinstance(field, dm.TimeField):
        return datetime.time(10, 0)
    if isinstance(field, dm.JSONField):
        return {}
    if isinstance(field, dm.UUIDField):
        return uuid.uuid4()
    if isinstance(field, dm.CharField):
        if field.choices:
            return field.choices[0][0]
        return ('x%d' % n)[:field.max_length or 10]
    if isinstance(field, dm.TextField):
        return 'x'
    return None


def node_of(o):
    return o.node_id if hasattr(o, 'node_id') else o.period.node_id


def make(testcase, model, node, n=0, **kw):
    """Fabrique generique : remplit les champs obligatoires sans valeur par defaut."""
    data = dict(kw)
    for f in model._meta.concrete_fields:
        if f.primary_key and not isinstance(f, dm.UUIDField):
            continue
        if f.name in data or f.has_default() or f.null or isinstance(f, dm.AutoField):
            continue
        if getattr(f, 'auto_now', False) or getattr(f, 'auto_now_add', False):
            continue
        if isinstance(f, dm.ForeignKey):
            rel = f.related_model
            if rel.__name__ == 'Node':
                data[f.name] = node
            elif rel.__name__ == 'User':
                data[f.name] = testcase.u['GERANT']
            elif rel.__name__ == 'Client':
                data[f.name] = testcase.c1 if node == testcase.k1 else testcase.c2
            else:
                existing = rel.objects.filter(node=node).first() if any(
                    x.name == 'node' for x in rel._meta.concrete_fields) else None
                data[f.name] = existing or make(testcase, rel, node, n)
            continue
        if f.blank and isinstance(f, (dm.CharField, dm.TextField)):
            continue
        v = _value(f, n)
        if v is not None:
            data[f.name] = v
    return model.objects.create(**data)


class Bug313Viewsets(Base):
    def _obj(self, app, name, node, n):
        model = apps.get_model(app, name)
        kw = {}
        if name == 'ClientCommission':
            from commissions.models import CommissionPeriod
            kw['period'] = CommissionPeriod.objects.create(node=node, month=3 + n, year=2026)
            kw['client'] = self.c1 if node == self.k1 else self.c2
        if name == 'CommissionPeriod':
            kw.update(month=7 + n, year=2025)
        return make(self, model, node, n, **kw)

    def test_all_viewsets_node_immutable_for_gerant(self):
        g = cl(self.u['GERANT'])
        problems = []
        for i, (app, name, url) in enumerate(TARGETS):
            try:
                with transaction.atomic():
                    o1 = self._obj(app, name, self.k1, 1)
                    o2 = self._obj(app, name, self.k2, 2)
            except Exception as e:  # fabrique impossible -> signale, ne masque pas
                problems.append(f'{name}: fabrique KO ({type(e).__name__}: {e})')
                continue
            detail = f'{url}{o1.pk}/'
            r = g.get(detail)
            if r.status_code == 403 and name == 'DisbursementVoucher':
                continue  # reserve au siege : un gerant n'a aucun acces (voir test siege)
            if r.status_code != 200:
                problems.append(f'{name}: GET detail propre objet = {r.status_code}')
                continue
            # K2 invisible
            r2 = g.get(f'{url}{o2.pk}/')
            if r2.status_code not in (403, 404):
                problems.append(f'FUITE {name}: GET objet K2 = {r2.status_code}')
            for verb in ('patch', 'put'):
                body = {'node': str(self.k2.pk)} if verb == 'patch' else dict(r.data, node=str(self.k2.pk))
                resp = getattr(g, verb)(detail, body, format='json')
                if resp.status_code >= 500:
                    problems.append(f'{name} {verb}: 5xx')
                o1 = type(o1).objects.get(pk=o1.pk)
                if node_of(o1) != self.k1.pk:
                    problems.append(f'BLOQUANT {name} {verb}: node deplace vers K2 (status {resp.status_code})')
                    pass
            # DELETE / PATCH sur objet K2
            for verb in ('patch', 'delete'):
                resp = getattr(g, verb)(f'{url}{o2.pk}/', {'node': str(self.k1.pk)}, format='json')
                o2 = type(o2).objects.get(pk=o2.pk)
                if node_of(o2) != self.k2.pk:
                    problems.append(f'BLOQUANT {name} {verb} sur K2: node change')
                if resp.status_code not in (400, 403, 404, 405):
                    problems.append(f'FUITE {name} {verb} sur objet K2 = {resp.status_code}')
        self.assertEqual(problems, [], '\n'.join(problems))

    def test_hq_patch_node_no_5xx(self):
        d = cl(self.u['DIRECTION'])
        problems = []
        for app, name, url in TARGETS:
            try:
                with transaction.atomic():
                    o1 = self._obj(app, name, self.k1, 3)
            except Exception as e:
                problems.append(f'{name}: fabrique KO {e}')
                continue
            resp = d.patch(f'{url}{o1.pk}/', {'node': str(self.k1.pk)}, format='json')
            if resp.status_code >= 500:
                problems.append(f'{name}: siege patch 5xx')
        self.assertEqual(problems, [], '\n'.join(problems))

    def test_gerant_post_with_forged_node_never_creates_in_k2(self):
        g = cl(self.u['GERANT'])
        from clients.models import SocialContribution, SocialDistribution
        r = g.post('/api/clients/distributions/', {'node': str(self.k2.pk), 'year': 2040, 'tarif': '10'},
                   format='json')
        self.assertFalse(SocialDistribution.objects.filter(node=self.k2, year=2040).exists(), r.content)
        r = g.post('/api/clients/contributions/', {'node': str(self.k2.pk), 'client': str(self.c2.pk),
                                                    'month': 2, 'year': 2026, 'amount': '10'}, format='json')
        self.assertFalse(SocialContribution.objects.filter(node=self.k2, month=2, year=2026,
                                                           client=self.c2).exists(), r.content)


class Bug313ClosedDistribution(Base):
    def test_gerant_cannot_reopen_closed_distribution(self):
        from clients.models import SocialDistribution
        SocialDistribution.objects.filter(pk=self.dist1.pk).update(is_closed=True)
        g = cl(self.u['GERANT'])
        for verb, body in (('patch', {'is_closed': False}),
                           ('put', {'node': str(self.k1.pk), 'year': 2026, 'tarif': '700', 'is_closed': False})):
            getattr(g, verb)(f'/api/clients/distributions/{self.dist1.pk}/', body, format='json')
            self.dist1.refresh_from_db()
            self.assertTrue(self.dist1.is_closed, verb)

    def test_gerant_cannot_change_tarif_or_year_of_closed(self):
        from clients.models import SocialDistribution
        SocialDistribution.objects.filter(pk=self.dist1.pk).update(is_closed=True)
        g = cl(self.u['GERANT'])
        g.patch(f'/api/clients/distributions/{self.dist1.pk}/', {'tarif': '1'}, format='json')
        g.patch(f'/api/clients/distributions/{self.dist1.pk}/', {'year': 2031}, format='json')
        self.dist1.refresh_from_db()
        self.assertEqual((self.dist1.tarif, self.dist1.year), (Dc('700'), 2026))

    def test_gerant_can_close_but_it_is_via_patch_flag(self):
        """Information : un gerant peut poser is_closed=True par PATCH (cloture voulue, irreversible)."""
        g = cl(self.u['GERANT'])
        r = g.patch(f'/api/clients/distributions/{self.dist1.pk}/', {'is_closed': True}, format='json')
        self.assertIn(r.status_code, (200, 400, 403), r.content)


class Bug316TarifEtCloture(Base):
    """BUG-316 : le TARIF (adaptes.md [4.2] : « fixe par la direction ») et la
    cloture irreversible d'une distribution sont modifiables par un gerant."""

    def test_gerant_cannot_set_tarif_of_open_distribution(self):
        cl(self.u['GERANT']).patch(f'/api/clients/distributions/{self.dist1.pk}/', {'tarif': '99999'}, format='json')
        self.dist1.refresh_from_db()
        self.assertEqual(self.dist1.tarif, Dc('700'))

    def test_gerant_cannot_close_distribution(self):
        cl(self.u['GERANT']).patch(f'/api/clients/distributions/{self.dist1.pk}/', {'is_closed': True}, format='json')
        self.dist1.refresh_from_db()
        self.assertFalse(self.dist1.is_closed)

    def test_gerant_gets_403_french_detail_on_tarif_and_close(self):
        g = cl(self.u['GERANT'])
        for body in ({'tarif': '99999'}, {'is_closed': True}):
            r = g.patch(f'/api/clients/distributions/{self.dist1.pk}/', body, format='json')
            self.assertEqual(r.status_code, 403, r.content)
            self.assertIn('direction', r.data['detail'])
        self.dist1.refresh_from_db()
        self.assertEqual((self.dist1.tarif, self.dist1.is_closed), (Dc('700'), False))

    def test_gerant_put_unchanged_tarif_and_closed_still_ok(self):
        r = cl(self.u['GERANT']).patch(f'/api/clients/distributions/{self.dist1.pk}/',
                                       {'tarif': '700', 'is_closed': False}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_gerant_create_ignores_custom_tarif_and_closed(self):
        from clients.models import SocialDistribution
        r = cl(self.u['GERANT']).post('/api/clients/distributions/',
                                      {'node': str(self.k1.pk), 'year': 2041, 'tarif': '5000',
                                       'is_closed': True}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        d = SocialDistribution.objects.get(year=2041)
        self.assertEqual((d.tarif, d.is_closed), (Dc('700'), False))

    def test_direction_create_keeps_custom_tarif(self):
        from clients.models import SocialDistribution
        r = cl(self.u['DIRECTION']).post('/api/clients/distributions/',
                                         {'node': str(self.k1.pk), 'year': 2042, 'tarif': '650'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(SocialDistribution.objects.get(year=2042).tarif, Dc('650'))

    def test_direction_can_set_tarif_and_close(self):
        r = cl(self.u['DIRECTION']).patch(f'/api/clients/distributions/{self.dist1.pk}/',
                                          {'tarif': '800', 'is_closed': True}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.dist1.refresh_from_db()
        self.assertEqual((self.dist1.tarif, self.dist1.is_closed), (Dc('800'), True))


class Bug314Values(Base):
    def test_negative_and_garbage_values_rejected(self):
        d = cl(self.u['DIRECTION'])
        for field in ('monthly_social_contribution', 'sac_value_fc'):
            for bad in ('-1', '-0.01', 'abc', 'NaN', 'Infinity', '1e99', '9' * 30):
                r = d.patch(f'/api/core/nodes/{self.k1.pk}/', {field: bad}, format='json')
                self.assertEqual(r.status_code, 400, (field, bad, r.content))

    def test_gerant_cannot_patch_node_values(self):
        r = cl(self.u['GERANT']).patch(f'/api/core/nodes/{self.k1.pk}/',
                                       {'monthly_social_contribution': '5'}, format='json')
        self.assertIn(r.status_code, (403, 405))
        r = cl(self.u['GERANT']).post('/api/core/nodes/', {'code': 'ZZ8', 'name': 'x',
                                                           'sac_value_fc': '-5'}, format='json')
        self.assertIn(r.status_code, (400, 403))

    def test_valid_values_still_accepted(self):
        d = cl(self.u['DIRECTION'])
        for field, val in (('monthly_social_contribution', '2500'), ('sac_value_fc', '200000')):
            r = d.patch(f'/api/core/nodes/{self.k1.pk}/', {field: val}, format='json')
            self.assertEqual(r.status_code, 200, r.content)

    def test_negative_on_creation_rejected(self):
        r = cl(self.u['DIRECTION']).post('/api/core/nodes/', {'code': 'ZZ7', 'name': 'y',
                                                              'monthly_social_contribution': '-3'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
