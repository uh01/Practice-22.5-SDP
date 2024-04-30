from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.http import HttpResponse
from django.views.generic import CreateView, ListView
from transactions.constants import DEPOSIT, WITHDRAWAL,LOAN, LOAN_PAID, TRANSFER
from datetime import datetime
from django.db.models import Sum
from transactions.forms import (
    DepositForm,
    WithdrawForm,
    LoanRequestForm,
    MoneyTransferForm,
)
from transactions.models import Transaction
from accounts.models import UserBankAccount

class TransactionCreateMixin(LoginRequiredMixin, CreateView):
    template_name = 'transactions/transaction_form.html'
    model = Transaction
    title = ''
    success_url = reverse_lazy('transaction_report')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update({
            'account': self.request.user.account
        })
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': self.title
        })

        return context


class DepositMoneyView(TransactionCreateMixin):
    form_class = DepositForm
    title = 'Deposit'

    def get_initial(self):
        initial = {'transaction_type': DEPOSIT}
        return initial

    def form_valid(self, form):
        amount = form.cleaned_data.get('amount')
        account = self.request.user.account
        account.balance += amount
        account.save(
            update_fields=[
                'balance'
            ]
        )

        messages.success(
            self.request,
            f'{"{:,.2f}".format(float(amount))}$ was deposited to your account successfully'
        )

        return super().form_valid(form)


class WithdrawMoneyView(TransactionCreateMixin):
    form_class = WithdrawForm
    title = 'Withdraw Money'

    def get_initial(self):
        initial = {'transaction_type': WITHDRAWAL}
        return initial

    def form_valid(self, form):
        amount = form.cleaned_data.get('amount')
        
        if amount > self.request.user.account.balance:
            messages.error(self.request, f'The bank is bankrupt. Unable to withdraw funds.')
            return redirect('withdraw_money')

        else:
          self.request.user.account.balance -= amount
          self.request.user.account.save(update_fields=['balance'])

          messages.success(
            self.request,
            f'Successfully withdrawn {"{:,.2f}".format(float(amount))}$ from your account'
            )

        return super().form_valid(form)
    

class LoanRequestView(TransactionCreateMixin):
    form_class = LoanRequestForm
    title = 'Request For Loan'

    def get_initial(self):
        initial = {'transaction_type': LOAN}
        return initial

    def form_valid(self, form):
        amount = form.cleaned_data.get('amount')
        current_loan_count = Transaction.objects.filter(
            account=self.request.user.account,transaction_type=3,loan_approve=True).count()
        if current_loan_count >= 3:
            return HttpResponse("You have cross the loan limits")
        messages.success(
            self.request,
            f'Loan request for {"{:,.2f}".format(float(amount))}$ submitted successfully'
        )

        return super().form_valid(form)
    

class TransactionReportView(LoginRequiredMixin, ListView):
    template_name = 'transactions/transaction_report.html'
    model = Transaction
    balance = 0
    
    def get_queryset(self):
        queryset = super().get_queryset().filter(
            account=self.request.user.account
        )
        start_date_str = self.request.GET.get('start_date')
        end_date_str = self.request.GET.get('end_date')
        
        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            queryset = queryset.filter(timestamp__date__gte=start_date, timestamp__date__lte=end_date)
            self.balance = Transaction.objects.filter(
                timestamp__date__gte=start_date, timestamp__date__lte=end_date
            ).aggregate(Sum('amount'))['amount__sum']
        else:
            self.balance = self.request.user.account.balance
       
        return queryset.distinct()
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'account': self.request.user.account
        })

        return context
    
        
class PayLoanView(LoginRequiredMixin, View):
    def get(self, request, loan_id):
        loan = get_object_or_404(Transaction, id=loan_id)
        print(loan)
        if loan.loan_approve:
            user_account = loan.account
            if loan.amount < user_account.balance:
                user_account.balance -= loan.amount
                loan.balance_after_transaction = user_account.balance
                user_account.save()
                loan.loan_approved = True
                loan.transaction_type = LOAN_PAID
                loan.save()
                return redirect('loan_list')
            else:
                messages.error(
            self.request,
            f'Loan amount is greater than available balance'
        )

        return redirect('loan_list')



class LoanListView(LoginRequiredMixin,ListView):
    model = Transaction
    template_name = 'transactions/loan_request.html'
    context_object_name = 'loans'
    
    def get_queryset(self):
        user_account = self.request.user.account
        queryset = Transaction.objects.filter(account=user_account,transaction_type=3)
        print(queryset)
        return queryset
    


class TransferMoneyView(LoginRequiredMixin, View):
    template_name = 'transactions/transfer_money.html'

    def get(self, request, *args, **kwargs):
        form = MoneyTransferForm(account=request.user.account)
        return render(request, self.template_name, {'form': form})

    def post(self, request, *args, **kwargs):
        form = MoneyTransferForm(request.POST, account=request.user.account)

        if form.is_valid():
            amount = form.cleaned_data.get('amount')
            target_account_number = form.cleaned_data.get('target_account_number')

            source_account = request.user.account

            try:
                target_account = UserBankAccount.objects.get(account_no=target_account_number)
            except UserBankAccount.DoesNotExist:
                messages.error(request, f'Account number {target_account_number} does not exist.')
                return render(request, self.template_name, {'form': form})

            if source_account.balance >= amount:
                source_account.balance -= amount
                target_account.balance += amount

                source_account.save(update_fields=['balance'])
                target_account.save(update_fields=['balance'])

                Transaction.objects.create(
                    account=source_account,
                    amount=amount, 
                    balance_after_transaction=source_account.balance,
                    transaction_type=TRANSFER
                )

                Transaction.objects.create(
                    account=target_account,
                    amount=amount,
                    balance_after_transaction=target_account.balance,
                    transaction_type=TRANSFER
                )

                messages.success(
                    request,f'Successfully transferred {"{:,.2f}".format(float(amount))}$ to account {target_account_number}'
                )
                
            else:
                messages.error(
                    request,'Insufficient funds. Unable to transfer money.'
                )
                return redirect('transfer_money')

            return redirect('transaction_report')
        

        else:
          return render(request, self.template_name, {'form': form})


