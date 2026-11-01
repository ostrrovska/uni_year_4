# Протокол роботи підсистеми реєстрації

Лівий стовпчик — дія користувача, правий — її відображення в журналі аудиту.

Записів: **37**. Цілісність журналу: **підтверджена** (chain intact, 37 record(s)).

| Дія користувача | Запис у журналі аудиту |
|---|---|
| *(система)* access control service started on 127.0.0.1:5707 | `#1` &nbsp; 2026-10-28 14:38:23.292<br>**SYSTEM / SUCCESS**<br>вердикт: objects: 12, auditor: kovalenko |
| **ostrovska** пред'явив токен і пройшов аутентифікацію<br>`authenticate as 'ostrovska'` | `#2` &nbsp; 2026-10-28 14:38:24.150<br>**AUTH / SUCCESS**<br>джерело: `127.0.0.1:56396`<br>вердикт: hash image matches the database |
| **ostrovska** відкрив сесію<br>`open session` | `#3` &nbsp; 2026-10-28 14:38:24.177<br>**SESSION / SUCCESS**<br>джерело: `127.0.0.1:56396`<br>вердикт: authentication passed |
| **ostrovska** спробував прочитати об'єкт `finance_q1`<br>`read finance_q1` | `#4` &nbsp; 2026-10-28 14:38:24.218<br>**ACCESS / SUCCESS**<br>джерело: `127.0.0.1:56396`<br>вердикт: right 'read' on 'finance_q1' is present (as owner) |
| **ostrovska** спробував дописати в об'єкт `finance_q1`<br>`write finance_q1 "quarterly revenue 1 200 000 UAH"` | `#5` &nbsp; 2026-10-28 14:38:24.251<br>**ACCESS / SUCCESS**<br>джерело: `127.0.0.1:56396`<br>вердикт: right 'write' on 'finance_q1' is present (as owner) |
| **ostrovska** спробував прочитати об'єкт `lab_report`<br>`read lab_report` | `#6` &nbsp; 2026-10-28 14:38:24.280<br>**ACCESS / FAILURE**<br>джерело: `127.0.0.1:56396`<br>вердикт: subject 'ostrovska' has no right 'read' on 'lab_report' |
| **ostrovska** спробував видалити об'єкт `lab_report`<br>`delete lab_report` | `#7` &nbsp; 2026-10-28 14:38:24.312<br>**ACCESS / FAILURE**<br>джерело: `127.0.0.1:56396`<br>вердикт: subject 'ostrovska' has no right 'delete' on 'lab_report' |
| **ostrovska** спробував прочитати об'єкт `poems`<br>`read poems` | `#8` &nbsp; 2026-10-28 14:38:24.342<br>**ACCESS / FAILURE**<br>джерело: `127.0.0.1:56396`<br>вердикт: subject 'ostrovska' has no right 'read' on 'poems' |
| **ostrovska** завершив сесію<br>`close session` | `#9` &nbsp; 2026-10-28 14:38:24.373<br>**SESSION / SUCCESS**<br>джерело: `127.0.0.1:56396`<br>вердикт: session ended |
| **mallory** пред'явив токен і пройшов аутентифікацію<br>`authenticate as 'mallory'` | `#10` &nbsp; 2026-10-28 14:38:24.684<br>**AUTH / FAILURE**<br>джерело: `127.0.0.1:56397`<br>вердикт: unknown identifier 'mallory' |
| **ostrovska** пред'явив токен і пройшов аутентифікацію<br>`authenticate as 'ostrovska'` | `#11` &nbsp; 2026-10-28 14:38:25.013<br>**AUTH / FAILURE**<br>джерело: `127.0.0.1:56398`<br>вердикт: hash image does not match the database |
| **ostrovska** пред'явив токен і пройшов аутентифікацію<br>`authenticate as 'ostrovska'` | `#12` &nbsp; 2026-10-28 14:38:25.324<br>**AUTH / SUCCESS**<br>джерело: `127.0.0.1:56400`<br>вердикт: hash image matches the database |
| **ostrovska** відкрив сесію<br>`open session` | `#13` &nbsp; 2026-10-28 14:38:25.353<br>**SESSION / SUCCESS**<br>джерело: `127.0.0.1:56400`<br>вердикт: authentication passed |
| **ostrovska** спробував надати право `finance_q1`<br>`grant finance_q1 shevchenko read` | `#14` &nbsp; 2026-10-28 14:38:25.380<br>**RIGHTS / SUCCESS**<br>джерело: `127.0.0.1:56400`<br>вердикт: right 'read' on 'finance_q1' granted to 'shevchenko' |
| **ostrovska** спробував надати право `finance_q1`<br>`grant finance_q1 kovalenko grant` | `#15` &nbsp; 2026-10-28 14:38:25.427<br>**RIGHTS / SUCCESS**<br>джерело: `127.0.0.1:56400`<br>вердикт: right 'grant' on 'finance_q1' granted to 'kovalenko' |
| **ostrovska** завершив сесію<br>`close session` | `#16` &nbsp; 2026-10-28 14:38:25.465<br>**SESSION / SUCCESS**<br>джерело: `127.0.0.1:56400`<br>вердикт: session ended |
| **shevchenko** пред'явив токен і пройшов аутентифікацію<br>`authenticate as 'shevchenko'` | `#17` &nbsp; 2026-10-28 14:38:25.758<br>**AUTH / SUCCESS**<br>джерело: `127.0.0.1:56401`<br>вердикт: hash image matches the database |
| **shevchenko** відкрив сесію<br>`open session` | `#18` &nbsp; 2026-10-28 14:38:25.788<br>**SESSION / SUCCESS**<br>джерело: `127.0.0.1:56401`<br>вердикт: authentication passed |
| **shevchenko** спробував прочитати об'єкт `finance_q1`<br>`read finance_q1` | `#19` &nbsp; 2026-10-28 14:38:25.836<br>**ACCESS / SUCCESS**<br>джерело: `127.0.0.1:56401`<br>вердикт: right 'read' on 'finance_q1' is present |
| **shevchenko** спробував видалити об'єкт `finance_q1`<br>`delete finance_q1` | `#20` &nbsp; 2026-10-28 14:38:25.866<br>**ACCESS / FAILURE**<br>джерело: `127.0.0.1:56401`<br>вердикт: subject 'shevchenko' has no right 'delete' on 'finance_q1' |
| **shevchenko** завершив сесію<br>`close session` | `#21` &nbsp; 2026-10-28 14:38:25.897<br>**SESSION / SUCCESS**<br>джерело: `127.0.0.1:56401`<br>вердикт: session ended |
| **kovalenko** пред'явив токен і пройшов аутентифікацію<br>`authenticate as 'kovalenko'` | `#22` &nbsp; 2026-10-28 14:38:26.163<br>**AUTH / SUCCESS**<br>джерело: `127.0.0.1:56402`<br>вердикт: hash image matches the database |
| **kovalenko** відкрив сесію<br>`open session` | `#23` &nbsp; 2026-10-28 14:38:26.192<br>**SESSION / SUCCESS**<br>джерело: `127.0.0.1:56402`<br>вердикт: authentication passed |
| **kovalenko** спробував прочитати об'єкт `finance_q1`<br>`read finance_q1` | `#24` &nbsp; 2026-10-28 14:38:26.219<br>**ACCESS / FAILURE**<br>джерело: `127.0.0.1:56402`<br>вердикт: subject 'kovalenko' has no right 'read' on 'finance_q1' |
| **kovalenko** спробував надати право `finance_q1`<br>`grant finance_q1 kovalenko read` | `#25` &nbsp; 2026-10-28 14:38:26.251<br>**RIGHTS / SUCCESS**<br>джерело: `127.0.0.1:56402`<br>вердикт: right 'read' on 'finance_q1' granted to 'kovalenko' |
| **kovalenko** спробував прочитати об'єкт `finance_q1`<br>`read finance_q1` | `#26` &nbsp; 2026-10-28 14:38:26.298<br>**ACCESS / SUCCESS**<br>джерело: `127.0.0.1:56402`<br>вердикт: right 'read' on 'finance_q1' is present |
| **kovalenko** спробував надати право `finance_q1`<br>`grant finance_q1 kovalenko delete` | `#27` &nbsp; 2026-10-28 14:38:26.339<br>**RIGHTS / SUCCESS**<br>джерело: `127.0.0.1:56402`<br>вердикт: right 'delete' on 'finance_q1' granted to 'kovalenko' |
| **kovalenko** спробував видалити об'єкт `finance_q1`<br>`delete finance_q1` | `#28` &nbsp; 2026-10-28 14:38:26.386<br>**ACCESS / SUCCESS**<br>джерело: `127.0.0.1:56402`<br>вердикт: right 'delete' on 'finance_q1' is present -> object removed |
| **kovalenko** завершив сесію<br>`close session` | `#29` &nbsp; 2026-10-28 14:38:26.421<br>**SESSION / SUCCESS**<br>джерело: `127.0.0.1:56402`<br>вердикт: session ended |
| **shevchenko** пред'явив токен і пройшов аутентифікацію<br>`authenticate as 'shevchenko'` | `#30` &nbsp; 2026-10-28 14:38:26.665<br>**AUTH / SUCCESS**<br>джерело: `127.0.0.1:56403`<br>вердикт: hash image matches the database |
| **shevchenko** відкрив сесію<br>`open session` | `#31` &nbsp; 2026-10-28 14:38:26.696<br>**SESSION / SUCCESS**<br>джерело: `127.0.0.1:56403`<br>вердикт: authentication passed |
| **shevchenko** звернувся до журналу аудиту<br>`audit` | `#32` &nbsp; 2026-10-28 14:38:26.738<br>**AUDIT / FAILURE**<br>джерело: `127.0.0.1:56403`<br>вердикт: subject 'shevchenko' is not the auditor (the journal may be read by 'kovalenko') |
| **shevchenko** завершив сесію<br>`close session` | `#33` &nbsp; 2026-10-28 14:38:26.778<br>**SESSION / SUCCESS**<br>джерело: `127.0.0.1:56403`<br>вердикт: session ended |
| **kovalenko** пред'явив токен і пройшов аутентифікацію<br>`authenticate as 'kovalenko'` | `#34` &nbsp; 2026-10-28 14:38:26.997<br>**AUTH / SUCCESS**<br>джерело: `127.0.0.1:56404`<br>вердикт: hash image matches the database |
| **kovalenko** відкрив сесію<br>`open session` | `#35` &nbsp; 2026-10-28 14:38:27.048<br>**SESSION / SUCCESS**<br>джерело: `127.0.0.1:56404`<br>вердикт: authentication passed |
| **kovalenko** звернувся до журналу аудиту<br>`audit` | `#36` &nbsp; 2026-10-28 14:38:27.086<br>**AUDIT / SUCCESS**<br>джерело: `127.0.0.1:56404`<br>вердикт: 8 of 35 record(s) |
| **kovalenko** завершив сесію<br>`close session` | `#37` &nbsp; 2026-10-28 14:38:27.132<br>**SESSION / SUCCESS**<br>джерело: `127.0.0.1:56404`<br>вердикт: session ended |
