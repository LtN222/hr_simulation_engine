class Person:
    def __init__(
        self,
        gender,
        first_name,
        last_name,
        birth_date,
        country="Nederland"
    ):
        self.gender = gender
        self.first_name = first_name
        self.last_name = last_name
        self.birth_date = birth_date
        self.country = country

    def age(self, today):
        return (today - self.birth_date).days // 365