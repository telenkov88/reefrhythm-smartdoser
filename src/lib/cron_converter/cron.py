from .sub_modules.part import Part
from .sub_modules.units import units
from .sub_modules.seeker import Seeker

class Cron:
    """Creates an instance of Cron.

    Cron objects each represent a cron schedule.

    Attributes:
        options (dict): The options to use
    """

    def __init__(self, cron_string=None, options=None):
        self.options = options if bool(options) else dict()
        self.parts = None
        if cron_string:
            self.from_string(cron_string)

    def __str__(self):
        """Print directly the Cron Object"""
        return self.to_string()

    def __lt__(self, other):
        """This Cron object is lower than the other Cron.
        The comparison is made by comparing the number of Cron schedule times.
        """
        reordered_parts = self.parts[:3] + [self.parts[4], self.parts[3]]
        reordered_parts_other = other.parts[:3] + [other.parts[4], other.parts[3]]
        for part, other_part in zip(reversed(reordered_parts), reversed(reordered_parts_other)):
            if part < other_part:
                return True
            elif part > other_part:
                return False
        return False

    def __eq__(self, other):
        """This Cron object is equal to the other Cron.
        The comparison is made by comparing the number of Cron schedule times.
        """
        return all(part == other_part for part, other_part in zip(self.parts, other.parts))

    def __le__(self, other):
        """Less than or equal to comparison."""
        return self < other or self == other

    def __gt__(self, other):
        """Greater than comparison."""
        return not self <= other

    def __ge__(self, other):
        """Greater than or equal to comparison."""
        return not self < other

    def from_string(self, cron_string):
        """Parses a cron string (minutes - hours - days - months - weekday)

        :param cron_string: The cron string to parse. It has to be made up of 5 parts.
        :raises ValueError: Incorrect length of the cron string.
        """
        if not isinstance(cron_string, str):
            raise TypeError('Invalid cron string')
        self.parts = cron_string.strip().split()
        if len(self.parts) != 5:
            raise ValueError("Invalid cron string format")
        cron_parts = []
        for item, unit in zip(self.parts, units):
            part = Part(unit, self.options)
            part.from_string(item)
            cron_parts.append(part)

        self.parts = cron_parts

    def to_string(self):
        """Return the cron schedule as a string.

        :return: The cron schedule as a string.
        """
        if not self.parts:
            raise LookupError('No schedule found')
        return ' '.join(str(part) for part in self.parts)

    def from_list(self, cron_list):
        """Parses a 2-dimensional array of integers as a cron schedule.

        :param cron_list: The 2-dimensional list to parse.
        :raises ValueError: Incorrect length of the cron list.
        """
        cron_parts = []
        if len(cron_list) != 5:
            raise ValueError('Invalid cron list')

        for cron_part_list, unit in zip(cron_list, units):
            part = Part(unit, self.options)
            part.from_list(cron_part_list)
            cron_parts.append(part)

        self.parts = cron_parts

    def to_list(self):
        """Returns the cron schedule as a 2-dimensional list of integers

        :return: The cron schedule as a list.
        :raises LookupError: Empty Cron object.
        """
        if not self.parts:
            raise LookupError('No schedule found')
        schedule_list = []
        for part in self.parts:
            schedule_list.append(part.to_list())
        return schedule_list

    def schedule(self, start_date=None, timezone_str=None):
        """Returns the time the schedule would run next.

        :param start_date: Optional. A datetime object. If not provided, the date will be now in UTC.
                                     This parameter excludes 'timezone_str'.
        :param timezone_str: Optional. A timezone string ('Europe/Rome', 'America/New_York', ...). The date will be now, but localized.
                                       If not provided, the date will be now in UTC. This parameter excludes 'start_date'.
        :return: A schedule iterator.
        """
        return Seeker(self, start_date, timezone_str)

