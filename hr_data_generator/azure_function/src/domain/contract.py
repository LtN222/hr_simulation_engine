class Contract:
    def __init__(
        self,
        contract_type,
        start_date,
        end_date,
        hours,
        contract_round
    ):
        self.contract_type = contract_type
        self.start_date = start_date
        self.end_date = end_date
        self.hours = hours
        self.contract_round = contract_round

    def is_active(self, today):
        return self.end_date is None or self.end_date > today