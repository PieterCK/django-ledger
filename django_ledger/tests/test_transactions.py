from random import choice, randint
from decimal import Decimal
from django.db.utils import IntegrityError
from django.core.exceptions import ObjectDoesNotExist

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.forms import modelformset_factory, BaseModelFormSet
from django_ledger.forms.transactions import get_transactionmodel_formset_class, TransactionModelForm,TransactionModelFormSet

from django_ledger.models import TransactionModel, EntityModel, AccountModel, LedgerModel, JournalEntryModel
from django_ledger.tests.base import DjangoLedgerBaseTest

UserModel = get_user_model()

class TransactionModelFormTest(DjangoLedgerBaseTest):
    
    def test_valid_data(self):
        entity_model: EntityModel = choice(self.ENTITY_MODEL_QUERYSET)
        
        account_model = str(self.get_random_account(entity_model=entity_model,balance_type='credit').uuid),
        random_tx_type = choice([tx_type[0] for tx_type in TransactionModel.TX_TYPE])
        
        form_data={
            'account': account_model[0],
            'tx_type': random_tx_type,
            'amount': Decimal(randint(10000, 99999)),
            'description': "Bought Something ..."
        }
        form = TransactionModelForm(form_data)

        self.assertTrue(form.is_valid(), msg=f"Form is invalid with error: {form.errors}")
        with self.assertRaises(IntegrityError):
            form.save()

    def test_invalid_tx_type(self):
        account_model = choice(AccountModel.objects.filter(balance_type='credit'))
        form = TransactionModelForm({
            'account': account_model,
            'tx_type': 'crebit patty',
        })
        self.assertFalse(form.is_valid(), msg="tx_type other than credit / debit shouldn't be valid")

    def test_blank_data(self):
        form = TransactionModelForm()
        self.assertFalse(form.is_valid(), msg="Form without data is supposed to be invalid")

    def test_invalid_account(self):     
        with self.assertRaises(ObjectDoesNotExist):
            form = TransactionModelForm({
                'account': "Asset",
            })
            form.is_valid()
    
class TransactionModelFormSetTest(DjangoLedgerBaseTest):
   
    def get_random_txs_formsets(self, 
                           entity_model: EntityModel,
                           credit_account: AccountModel = None,
                           debit_account: AccountModel = None,
                           ledger_model: LedgerModel = None,
                           je_model: JournalEntryModel = None,
                           credit_amount = 0,
                           debit_amount = 0
                           ) -> type[BaseModelFormSet]:
        """
        Returns a TransactionModelFormSet with prefilled form data.
        """
        
        ledger_model: LedgerModel = self.get_random_ledger(entity_model=entity_model) if not ledger_model else ledger_model
        je_model: JournalEntryModel = self.get_random_je(entity_model=entity_model, ledger_model=ledger_model) if not je_model else je_model
        credit_account: AccountModel= self.get_random_account(entity_model=entity_model,balance_type='credit') if not credit_account else credit_account
        debit_account: AccountModel = self.get_random_account(entity_model=entity_model,balance_type='debit') if not debit_account else debit_account

        if credit_amount + debit_amount == 0:
            credit_amount = debit_amount = Decimal(randint(10000, 99999))

        form_data = {
            'form-TOTAL_FORMS': '2',
            'form-INITIAL_FORMS': '0',
            'form-0-account':str(credit_account.uuid),
            'form-0-tx_type': 'credit',
            'form-0-amount': credit_amount,
            'form-0-description': str(randint(1, 99)),
            'form-1-account':str(debit_account.uuid),
            'form-1-tx_type': 'debit',
            'form-1-amount': debit_amount,
            'form-1-description': str(randint(1, 99)),
        }
        transaction_model_form_set = modelformset_factory(
                                                        model=TransactionModel,
                                                        form=TransactionModelForm,
                                                        formset=TransactionModelFormSet,
                                                        can_delete=True
                                                        )
        
        return transaction_model_form_set(
            form_data,
            entity_slug=entity_model.slug,
            user_model=self.user_model,
            ledger_pk=ledger_model,
            je_model=je_model
        )
                        
    def test_valid_formset(self):
        """
        Saved Transaction instances should have identical detail with initial formset.
        """
        entity_model: EntityModel = choice(self.ENTITY_MODEL_QUERYSET)
        ledger_model: LedgerModel = self.get_random_ledger(entity_model=entity_model)
        je_model: JournalEntryModel = self.get_random_je(entity_model=entity_model, ledger_model=ledger_model)
        credit_account: AccountModel= self.get_random_account(entity_model=entity_model,balance_type='credit')
        debit_account: AccountModel= self.get_random_account(entity_model=entity_model,balance_type='debit')
        transaction_amount = str(Decimal(randint(10000, 99999)))
        
        txs_formset = self.get_random_txs_formsets(entity_model=entity_model,
                                                   je_model=je_model,
                                                   ledger_model=ledger_model,
                                                   credit_account=credit_account,
                                                   credit_amount=transaction_amount,
                                                   debit_account=debit_account,
                                                   debit_amount=transaction_amount
                                                   )
       
        self.assertTrue(txs_formset.is_valid(), msg=f"Formset is not valid, error: {txs_formset.errors}") 

        txs_instances = txs_formset.save(commit=False)
        for txs in txs_instances:
            if not txs.journal_entry_id:
                txs.journal_entry_id = je_model.uuid
        
        txs_instances = txs_formset.save()
        for txs in txs_instances:
            if txs.tx_type == 'credit':
                self.assertEqual(txs.account, credit_account,
                                 msg=f'Saved Transaction record has missmatched Credit Account from the submitted formset. Saved:{txs.account} | form:{credit_account}')

            elif txs.tx_type == 'debit':
                self.assertEqual(txs.account, debit_account, 
                                 msg=f'Saved Transaction record has missmatched Debit Account from the submitted formset. Saved:{txs.account} | form:{debit_account}')

            self.assertEqual(txs.amount, Decimal(transaction_amount), 
                                 msg=f'Saved Transaction record has missmatched total amount from the submitted formset. Saved:{txs.amount} | form:{transaction_amount}')


    def test_imbalance_transactions(self):
        """
        Imbalanced Transactions should be invalid.
        """
        entity_model: EntityModel = choice(self.ENTITY_MODEL_QUERYSET)
        
        txs_formset =  self.get_random_txs_formsets(entity_model=entity_model,
                                                    credit_amount=1000,
                                                    debit_amount=2000
                                                    )
        
        self.assertFalse(txs_formset.is_valid(), 
                         msg=f"Formset is supposed to be invalid because of imbalance transaction")
    
    def test_ledger_lock(self):
        """
        Transaction on locked a locked Ledger should fail.
        """
        entity_model: EntityModel = choice(self.ENTITY_MODEL_QUERYSET)
        ledger_model = self.get_random_ledger(entity_model=entity_model)
        je_model = self.get_random_je(entity_model=entity_model, ledger_model=ledger_model)
        ledger_model.post(commit=True)
        ledger_model.lock(commit=True)

        self.assertTrue(ledger_model.is_locked())
        
        txs_formset = self.get_random_txs_formsets(entity_model=entity_model,
                                                   je_model=je_model,
                                                   ledger_model=ledger_model,
                                                   )
        with self.assertRaises(ObjectDoesNotExist, 
                               msg="Shouldn't be able to add new transaction to a locked Ledger"):
            txs_formset.is_valid()

    def test_je_locked(self):
        """
        Transaction on locked a locked Journal Entry should fail.
        """
        entity_model: EntityModel = choice(self.ENTITY_MODEL_QUERYSET)
        ledger_model: LedgerModel = self.get_random_ledger(entity_model=entity_model)
        je_model: JournalEntryModel = self.get_random_je(entity_model=entity_model, ledger_model=ledger_model)
        je_model.mark_as_locked(commit=True)
        self.assertTrue(je_model.is_locked())
        
        txs_formset = self.get_random_txs_formsets(entity_model=entity_model,
                                                   je_model=je_model,
                                                   ledger_model=ledger_model,
                                                   )
        with self.assertRaises(ObjectDoesNotExist, 
                               msg="Shouldn't be able to add new transaction to a locked Journal Entry"):
            txs_formset.is_valid()

class GetTransactionModelFormSetClassTest(DjangoLedgerBaseTest):
   
    def test_unlocked_journal_entry_formset(self):
        """
        The Formset will contain 6 extra forms & delete fields if Journal Entry is unlocked.
        """
        entity_model: EntityModel = choice(self.ENTITY_MODEL_QUERYSET)
        ledger_model: LedgerModel = self.get_random_ledger(entity_model=entity_model)
        je_model: JournalEntryModel = self.get_random_je(entity_model=entity_model, ledger_model=ledger_model)
        
        transaction_model_form_set = get_transactionmodel_formset_class(journal_entry_model=je_model)
        txs_formset = transaction_model_form_set(
                                                user_model=self.user_model,
                                                je_model=je_model,
                                                ledger_pk=ledger_model,
                                                entity_slug=entity_model.slug,
                                                queryset=je_model.transactionmodel_set.all().order_by('account__code')
                                                )
                
        self.assertTrue(not je_model.is_locked(), 
                        msg="At this point in this test case, Journal Entry should be unlocked.")
        
        delete_field = '<input type="checkbox" name="form-0-DELETE" id="id_form-0-DELETE">'
        self.assertInHTML(delete_field, txs_formset.as_table(),
                        msg_prefix="Transactions Formset with unlocked Journal Entry should have `can_delete` enabled")
        
        self.assertEqual(len(txs_formset), 6,
                         msg="Transactions Formset with unlocked Journal Entry should have 6 extras")
        
        
    def test_locked_journal_entry_formset(self):
        """
        The Formset will contain no extra forms & only forms with Transaction if Journal Entry is locked.
        """
        entity_model: EntityModel = choice(self.ENTITY_MODEL_QUERYSET)
        ledger_model: LedgerModel = self.get_random_ledger(entity_model=entity_model)
        je_model: JournalEntryModel = self.get_random_je(entity_model=entity_model, ledger_model=ledger_model)
        transaction_pairs= randint(1,12)
        self.get_random_transactions(entity_model=entity_model, je_model=je_model,pairs=transaction_pairs) # Fill Journal Entry with Transactions

        je_model.mark_as_locked(commit=True)
        self.assertTrue(je_model.is_locked(), 
                        msg="Journal Entry should be locked in this test case")
        
        transaction_model_form_set = get_transactionmodel_formset_class(journal_entry_model=je_model)
        
        txs_formset = transaction_model_form_set(
                                                user_model=self.user_model,
                                                je_model=je_model,
                                                ledger_pk=ledger_model,
                                                entity_slug=entity_model.slug,
                                                queryset=je_model.transactionmodel_set.all().order_by('account__code')
                                                )
                
        self.assertEqual(len(txs_formset), (transaction_pairs * 2), # Convert pairs to total count
                         msg="Transactions Formset with unlocked Journal Entry did not match the expected count")
