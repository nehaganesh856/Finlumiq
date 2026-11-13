import unittest
from decimal import Decimal
from name_based_split import _shares, _money

class SplitTests(unittest.TestCase):
    def test_equal_with_remainder(self):
        shares = _shares(Decimal('100.00'), [3, 1, 2], 'equal', [])
        self.assertEqual(sum((amount for _, amount in shares), Decimal('0.00')), Decimal('100.00'))
        self.assertEqual(shares, [(1, Decimal('33.34')), (2, Decimal('33.33')), (3, Decimal('33.33'))])

    def test_equal_normal(self):
        shares = _shares(Decimal('900.00'), [1, 2, 3], 'equal', [])
        self.assertEqual([amount for _, amount in shares], [Decimal('300.00')] * 3)

    def test_custom_requires_exact_total(self):
        with self.assertRaises(ValueError):
            _shares(Decimal('100.00'), [1, 2], 'custom', [
                {'person_id': 1, 'amount': '30.00'}, {'person_id': 2, 'amount': '69.99'}
            ])

    def test_percentage(self):
        shares = _shares(Decimal('100.00'), [1, 2, 3], 'percentage', [
            {'person_id': 1, 'percentage': '20'},
            {'person_id': 2, 'percentage': '30'},
            {'person_id': 3, 'percentage': '50'},
        ])
        self.assertEqual(sum((amount for _, amount in shares), Decimal('0.00')), Decimal('100.00'))
        self.assertEqual([amount for _, amount in shares], [Decimal('20.00'), Decimal('30.00'), Decimal('50.00')])

    def test_one_third_percentages_round(self):
        shares = _shares(Decimal('10.00'), [1, 2, 3], 'percentage', [
            {'person_id': 1, 'percentage': '33.34'},
            {'person_id': 2, 'percentage': '33.33'},
            {'person_id': 3, 'percentage': '33.33'},
        ])
        self.assertEqual(sum((amount for _, amount in shares), Decimal('0.00')), Decimal('10.00'))

    def test_money_rejects_too_many_decimals(self):
        with self.assertRaises(ValueError):
            _money('2.345')

if __name__ == '__main__':
    unittest.main()
