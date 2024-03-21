from lib.cron_converter import Cron
cron_instance = Cron()
cron_instance.from_string('*/10 9-17 1 * *')
print(cron_instance)
print(cron_instance.to_string())
print(cron_instance.to_list())