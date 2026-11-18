"""Создаёт статические страницы GitHub Pages из понятных блоков текста.

Запуск: python scripts/build_legal_site.py
Для обновления политики меняйте текст ниже и дату, затем запускайте скрипт.
Здесь только публичная информация; ключи API и данные приложения не читаются.
"""

from html import escape
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs"
EMAIL = "chippolinno622@gmail.com"
REPO = "https://github.com/matthew-mbn/CLIP-TRIBUNE"
SITE = "https://matthew-mbn.github.io/CLIP-TRIBUNE/"
DATE = "2026-11-18"
CONTACT = f'<a href="mailto:{EMAIL}">{EMAIL}</a>'
OWNER = '<a href="https://github.com/matthew-mbn">matthew-mbn</a>'

# Третий элемент каждого блока — статический HTML, написанный разработчиком.
# В него не подставляется пользовательский ввод.
PRIVACY_EN = [
    (
        "overview",
        "1. Who we are and what this covers",
        f"""
    <p>This policy explains the data practices of CLIP TRIBUNE, a Windows desktop video editor,
    and this project website. The project is maintained by {OWNER}. Privacy contact: {CONTACT}.</p>
    <p>Local editing does not require a CLIP TRIBUNE account. The maintainer does not operate a
    cloud library for your videos or receive your local projects through the app. Online features
    connect from your computer to the services you choose.</p>""",
    ),
    (
        "local",
        "2. Data stored on your computer",
        """
    <p>The app stores imported or downloaded media, advertising assets you provide, rendered clips,
    thumbnails, subtitles, filenames and paths, editing settings, project and job history,
    errors and diagnostic logs. It also stores the account and API data described below.</p>
    <p>Live recording stores the stream URL, title, recording times and local media segments.
    Automatic clipping analyzes completed segments on your computer and retains generated clips.
    The recorded parts remain until you delete them. Starting a recording does not publish its clips.</p>
    <p>The Windows EXE normally uses <code>%LOCALAPPDATA%\\CLIP TRIBUNE\\storage</code>.
    Running from source normally uses the project's <code>storage</code> folder. Advanced settings
    can change the storage or database location. Files and history remain until you remove them;
    closing or uninstalling the EXE does not automatically erase this folder.</p>
    <p>The app has no built-in usage analytics, advertising trackers or automatic crash reporting
    to the maintainer. The advertising feature overlays media that you supply; it is not an ad network.</p>""",
    ),
    (
        "platforms",
        "3. YouTube, TikTok and downloads",
        """
    <p><strong>YouTube:</strong> CLIP TRIBUNE uses YouTube API Services. With your authorization,
    it receives OAuth tokens, your channel ID, channel name and channel statistics. It sends videos
    and the titles, descriptions, tags and publication settings you select, and stores upload IDs,
    progress and processing results locally. Trend searches send your search and region parameters
    to YouTube and store returned public video metadata and statistics locally.</p>
    <p><strong>TikTok:</strong> with your authorization, the app receives OAuth tokens, your app-specific
    account ID and display name. It queries creator information and posting options when needed,
    sends the selected video and posting settings, and stores upload/publish IDs, results and history
    locally. Upload-to-inbox and Direct Post use the permissions you authorize.</p>
    <p>Login occurs on the platform's authorization page in your browser. CLIP TRIBUNE does not ask
    for your Google or TikTok password. A task you explicitly schedule can run later while the app
    is running. The destination platform processes the uploaded content under its own rules.</p>
    <p><strong>Downloads:</strong> downloading a supported YouTube or Twitch video sends requests
    to that platform and its media servers. They receive your IP address and normal connection
    information. The desktop downloader does not import your browser's cookies.</p>
    <p>Read the <a href="https://policies.google.com/privacy">Google Privacy Policy</a>,
    <a href="https://www.tiktok.com/legal/privacy-policy">TikTok Privacy Policy</a> applicable to
    your region, and <a href="https://legal.twitch.com/en/legal/privacy-notice/">Twitch Privacy Notice</a>.</p>""",
    ),
    (
        "providers",
        "4. Optional speech and AI services",
        """
    <p>If you configure a speech service and enable subtitles, the app sends the source media file
    to your configured speech endpoint to obtain a transcript. For live clips, this can be a window
    assembled from recorded segments. A cloud endpoint therefore receives
    that media; a service you run locally processes it at that local endpoint.</p>
    <p>If you configure an AI metadata endpoint and model, metadata generation sends the topic,
    selection evidence and available transcript to that endpoint. This request does not attach the
    video file. The endpoint also receives its configured authentication credential.</p>
    <p>These endpoints are empty by default. Review your chosen provider's privacy and retention
    terms before enabling it. The maintainer does not receive these requests, sell the data, use it
    for advertising or use it to train models. Independently chosen providers have their own practices.</p>""",
    ),
    (
        "security",
        "5. Credentials and security",
        """
    <p>OAuth tokens and secrets saved through the app's settings are encrypted in the local database.
    The encryption key is a separate file in the storage folder. This is not full-disk encryption:
    someone with access to the database and key can decrypt the secrets. Media and ordinary project
    records are not encrypted by this feature. Credentials you place in a <code>.env</code> file
    remain in that file as plain text.</p>
    <p>Protect your Windows account, backups and storage directory. Do not publish tokens, OAuth
    credential files, the database or encryption key. No method of storage or transmission is
    completely secure.</p>""",
    ),
    (
        "deletion",
        "6. Disconnecting, retention and deletion",
        """
    <p>Use <strong>Disconnect</strong> on the corresponding publishing page to revoke the app's
    platform access. YouTube disconnect removes the local channel record and tokens; TikTok
    disconnect clears the tokens. Some account identifiers and publication history can remain
    locally, especially TikTok history. Disconnecting is not a complete local-data wipe.</p>
    <p>You can also revoke Google access through
    <a href="https://security.google.com/settings/security/permissions">Google's security settings</a>
    and TikTok access through TikTok's connected-app controls. Revocation on a platform stops
    authorized access but does not remotely erase files on your computer.</p>
    <ol><li>For a full local reset, first save any videos you want to keep outside the app's data folder.</li>
    <li>Disconnect linked accounts, stop pending work and completely exit CLIP TRIBUNE.</li>
    <li>Delete the app's <code>storage</code> folder at the location above. This removes the local
    database, tokens, history and media stored there. Also remove any separate <code>.env</code>,
    downloaded OAuth credentials, custom data locations or backups that you no longer want.</li></ol>
    <p>The app cannot erase separately exported copies or platform-hosted posts through this reset.
    Manage published videos in YouTube or TikTok. The maintainer cannot remotely access or delete
    your local files. Email the contact below for help or to request deletion of information you
    supplied to the maintainer.</p>""",
    ),
    (
        "website",
        "7. Website visits and support messages",
        f"""
    <p>This static website uses no analytics scripts, tracking pixels, third-party fonts or cookies
    set by the project. GitHub Pages hosts it. GitHub logs visitors' IP addresses for security and
    processes hosting requests under the
    <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement">GitHub Privacy Statement</a>.
    Following links to GitHub or other services is subject to their own policies.</p>
    <p>If you email {CONTACT}, the maintainer and email service receive your address, message and
    any attachments you choose to send. They are used to answer the request and retained only as
    needed to handle it and meet applicable obligations. You may request deletion. Do not send
    passwords or tokens. Public GitHub issues are visible to everyone; use email for private matters.</p>""",
    ),
    (
        "rights",
        "8. Your choices and policy updates",
        f"""
    <p>You can use local editing without connecting platforms or AI providers. Depending on your
    location, you may have rights to access, correct, delete, restrict or object to processing of
    your personal information, or obtain a copy. Contact {CONTACT} about information held by the
    maintainer; contact the relevant platform for information it holds. You may also have the right
    to complain to your local data protection authority.</p>
    <p>The project is not intended for children under 13. Platform age requirements also apply.
    If you believe a child sent personal information to the maintainer, contact us.</p>
    <p>Updates to these practices will be described on this page with a revised date. This policy
    describes the current desktop app; it does not promise approval by any platform or certification
    under a particular privacy law.</p>""",
    ),
]

TERMS_EN = [
    (
        "agreement",
        "1. About these terms",
        f"""
    <p>These terms apply to your use of the CLIP TRIBUNE desktop application and project website,
    maintained by {OWNER}. Contact: {CONTACT}. By using the app, you agree to these terms.
    If you do not agree, do not use it. These terms do not remove rights that applicable law gives you.</p>
    <p>Read the <a href="privacy.html">Privacy Policy</a> for an explanation of local storage,
    optional online features and deletion. You must be legally able to agree to these terms or have
    the permission and supervision required by the law where you live.</p>""",
    ),
    (
        "service",
        "2. What the app provides",
        """
    <p>CLIP TRIBUNE is a Windows tool for editing clips, composing split-screen videos, adding
    user-provided overlays and using optional download and publishing integrations. Editing runs
    on your computer. The app is currently distributed without a subscription charge.</p>
    <p>You supply your own service credentials where required. External providers may impose fees,
    quotas, account requirements, review or geographic restrictions. Their availability is outside
    the maintainer's control. The app does not guarantee uninterrupted service, successful uploads,
    API approval, monetization or a particular audience response.</p>""",
    ),
    (
        "content",
        "3. Your content and responsibilities",
        """
    <p>You retain your rights in your source files and output. The maintainer does not claim ownership
    of them. Use only media, music, advertising assets and other material that you own or are
    authorized to download, edit and publish. A publicly accessible video is not automatically
    licensed for reuse.</p>
    <p>You are responsible for consent from relevant people, accurate descriptions, copyright and
    other applicable requirements. Review generated edits, captions and metadata before publication.
    Add required commercial-content, sponsorship or AI disclosures.</p>
    <p>Do not use the app to infringe rights, impersonate or deceive people, publish illegal material,
    spam services, evade access restrictions or bypass paywalls or technical protections. The
    availability of a feature does not grant permission to use third-party content.</p>""",
    ),
    (
        "platforms",
        "4. Connected services and publication",
        """
    <p>The app uses YouTube API Services. By using its YouTube features, you agree to be bound by the
    <a href="https://www.youtube.com/t/terms">YouTube Terms of Service</a>. TikTok features are
    subject to the <a href="https://www.tiktok.com/legal/terms-of-service">TikTok Terms of Service</a>
    applicable to your region and its publishing rules. Twitch use is subject to the
    <a href="https://legal.twitch.com/en/legal/terms-of-service/">Twitch Terms of Service</a>.</p>
    <p>You authorize the app to perform the actions you request using your connected accounts.
    Review the selected account, content and visibility before sending or scheduling a task.
    Uploading a TikTok inbox draft requires you to finish publication in TikTok. Direct posting
    depends on the permissions and account settings allowed by TikTok.</p>
    <p>Stopping or disconnecting the app cannot undo a file already accepted or a post already
    published by a platform. Manage those posts in the destination service. CLIP TRIBUNE is an
    independent project and is not endorsed by Google, YouTube, TikTok or Twitch.</p>""",
    ),
    (
        "software",
        "5. Software, backups and third-party components",
        f"""
    <p>Keep backups of important files and protect your credentials. You control your installation,
    configuration and local storage. Do not distribute copies that contain personal data or secrets.</p>
    <p>Third-party components retain their own licenses, described in the repository's
    <a href="{REPO}/blob/main/docs/third-party-notices.txt">component notices</a>.
    These terms do not replace or restrict rights granted by those licenses.</p>""",
    ),
    (
        "limits",
        "6. Availability and limitations",
        """
    <p>To the extent permitted by applicable law, the app is provided “as is” and “as available”,
    without warranties of fitness for a particular purpose or error-free operation. You are
    responsible for checking output and keeping backups before relying on it.</p>
    <p>To the extent permitted by applicable law, the maintainer is not liable for indirect or
    consequential losses, lost profits, loss of data or platform account actions arising from use
    of the app. Nothing here excludes liability or consumer rights that cannot lawfully be excluded.</p>""",
    ),
    (
        "ending",
        "7. Ending use and changes",
        f"""
    <p>You may stop using the app at any time, revoke connected services and remove local data using
    the <a href="privacy.html#deletion">deletion instructions</a>. The maintainer may update or
    discontinue the project. These terms may be updated with a new date on this page; review the
    current version before installing updates or enabling new online features.</p>
    <p>Questions about these terms or the project: {CONTACT}.</p>""",
    ),
]

PRIVACY_RU = [
    (
        "overview",
        "1. О проекте и этой политике",
        f"""
    <p>Эта политика описывает работу с данными в приложении CLIP TRIBUNE для Windows и на сайте
    проекта. Проект поддерживает {OWNER}. Контакт по вопросам конфиденциальности: {CONTACT}.</p>
    <p>Для локального монтажа не нужен аккаунт CLIP TRIBUNE. Разработчик не ведёт облачную библиотеку
    ваших видео и не получает локальные проекты через приложение. Онлайн-функции подключаются
    с вашего компьютера к выбранным вами сервисам.</p>""",
    ),
    (
        "local",
        "2. Данные на вашем компьютере",
        """
    <p>Приложение хранит импортированные и скачанные файлы, ваши рекламные материалы, готовые клипы,
    обложки, субтитры, имена и пути файлов, настройки монтажа, историю проектов и заданий,
    ошибки и диагностические журналы. Также локально хранятся данные подключений, описанные ниже.</p>
    <p>Запись эфира сохраняет ссылку, название, время записи и локальные части трансляции.
    Автоматическая нарезка анализирует закрытые части на компьютере и сохраняет готовые клипы.
    Части записи остаются до вашего удаления. Запуск записи не публикует созданные клипы.</p>
    <p>EXE обычно использует <code>%LOCALAPPDATA%\\CLIP TRIBUNE\\storage</code>, а запуск из исходников —
    папку <code>storage</code> проекта. Расширенные настройки позволяют изменить расположение
    хранилища или базы. Файлы и история остаются до удаления пользователем; закрытие или удаление
    EXE не стирает эту папку автоматически.</p>
    <p>В приложении нет встроенной аналитики использования, рекламных трекеров или автоматической
    отправки отчётов о сбоях разработчику. Раздел «Реклама» накладывает предоставленные вами
    материалы на видео и не является рекламной сетью.</p>""",
    ),
    (
        "platforms",
        "3. YouTube, TikTok и скачивание",
        """
    <p><strong>YouTube:</strong> CLIP TRIBUNE использует YouTube API Services. После вашего разрешения
    приложение получает OAuth-токены, идентификатор, название и статистику канала. При отправке
    передаются видео, выбранные названия, описания, теги и настройки публикации. Идентификаторы
    загрузок, прогресс и результаты обработки сохраняются локально. Поиск трендов передаёт YouTube
    поисковый запрос и регион, а полученные публичные сведения и статистика видео сохраняются локально.</p>
    <p><strong>TikTok:</strong> после разрешения приложение получает OAuth-токены, идентификатор
    аккаунта для приложения и отображаемое имя. При необходимости запрашивает информацию об авторе
    и доступных настройках публикации, передаёт выбранное видео и настройки. Идентификаторы
    загрузок и публикаций, результаты и история хранятся локально. Отправка во входящие и прямая
    публикация используют разрешения, которые вы предоставили.</p>
    <p>Вход происходит на странице самой платформы в браузере. CLIP TRIBUNE не запрашивает пароль
    Google или TikTok. Задание, которое вы назначили на определённое время, может выполниться
    позже, пока приложение работает. Получившая видео платформа обрабатывает его по своим правилам.</p>
    <p><strong>Скачивание:</strong> загрузка поддерживаемого видео YouTube или Twitch обращается
    к платформе и её серверам видео. Они получают ваш IP-адрес и обычные сведения о соединении.
    Загрузчик приложения не импортирует cookies из браузера.</p>
    <p>Ознакомьтесь с <a href="https://policies.google.com/privacy">политикой Google</a>,
    <a href="https://www.tiktok.com/legal/privacy-policy">политикой TikTok</a> для своего региона и
    <a href="https://legal.twitch.com/en/legal/privacy-notice/">политикой Twitch</a>.</p>""",
    ),
    (
        "providers",
        "4. Необязательные сервисы речи и AI",
        """
    <p>Если вы настроили сервис распознавания речи и включили субтитры, исходный медиафайл
    отправляется на указанный вами адрес для получения транскрипции. Для нарезки эфира это может
    быть окно, собранное из частей записи. Облачный сервис получает
    этот файл; сервис на вашем компьютере обрабатывает его по своему локальному адресу.</p>
    <p>Если настроены AI-сервис метаданных и модель, генератор передаёт тему, признаки отбора и
    имеющуюся транскрипцию. Сам видеофайл к этому запросу не прикрепляется. Сервис также получает
    настроенный для него ключ авторизации.</p>
    <p>По умолчанию адреса этих сервисов пустые. Перед подключением изучите правила обработки
    и хранения данных своего провайдера. Разработчик не получает эти запросы, не продаёт данные,
    не использует их для рекламы или обучения моделей. У выбранных вами провайдеров свои правила.</p>""",
    ),
    (
        "security",
        "5. Ключи и безопасность",
        """
    <p>OAuth-токены и секреты, сохранённые через настройки приложения, зашифрованы в локальной базе.
    Ключ шифрования находится в отдельном файле в папке хранилища. Это не шифрование всего диска:
    получив базу и ключ, можно расшифровать секреты. Медиа и обычные записи проектов этим механизмом
    не шифруются. Ключи, которые вы самостоятельно записали в <code>.env</code>, остаются в нём
    обычным текстом.</p>
    <p>Защищайте учётную запись Windows, резервные копии и хранилище. Не публикуйте токены,
    OAuth-файлы, базу и ключ шифрования. Абсолютно безопасных способов хранения и передачи нет.</p>""",
    ),
    (
        "deletion",
        "6. Отключение, хранение и удаление",
        """
    <p>Кнопка <strong>«Отключить»</strong> на соответствующей странице публикации отзывает доступ
    приложения. Отключение YouTube удаляет локальную запись канала и токены; отключение TikTok
    очищает токены. Часть идентификаторов и истории может остаться локально, особенно история
    TikTok. Отключение не означает полную очистку данных.</p>
    <p>Доступ Google также можно отозвать в
    <a href="https://security.google.com/settings/security/permissions">настройках безопасности Google</a>,
    а доступ TikTok — в настройках подключённых приложений TikTok. Отзыв на платформе прекращает
    разрешённый доступ, но не удаляет файлы на вашем компьютере дистанционно.</p>
    <ol><li>Для полного сброса сначала сохраните нужные видео вне папки данных приложения.</li>
    <li>Отключите аккаунты, остановите задания и полностью закройте CLIP TRIBUNE.</li>
    <li>Удалите папку <code>storage</code> по указанному выше пути. Будут удалены находящиеся в ней
    база, токены, история и медиа. Также удалите ненужные отдельные файлы <code>.env</code>,
    скачанные OAuth-ключи, дополнительные хранилища и резервные копии.</li></ol>
    <p>Этот сброс не удаляет отдельно экспортированные файлы и публикации на платформах.
    Управляйте опубликованными роликами в YouTube или TikTok. Разработчик не может дистанционно
    просматривать или удалять локальные файлы. По вопросам очистки и удаления сведений,
    которые вы отправили разработчику, пишите на контактный email.</p>""",
    ),
    (
        "website",
        "7. Сайт и обращения в поддержку",
        f"""
    <p>На этом статическом сайте нет скриптов аналитики, пикселей слежения, внешних шрифтов и
    cookies, устанавливаемых проектом. Сайт размещён на GitHub Pages. GitHub записывает IP-адреса
    посетителей для безопасности и обрабатывает запросы согласно
    <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement">своей политике конфиденциальности</a>.
    При переходе на GitHub и другие сервисы действуют их правила.</p>
    <p>При письме на {CONTACT} разработчик и почтовый сервис получают ваш адрес, текст и вложения,
    которые вы отправили. Они используются для ответа и хранятся столько, сколько необходимо
    для решения вопроса и выполнения применимых обязательств. Можно запросить удаление.
    Не присылайте пароли и токены. Публичные GitHub issues видны всем; для личных вопросов используйте email.</p>""",
    ),
    (
        "rights",
        "8. Ваш выбор и изменения политики",
        f"""
    <p>Можно пользоваться локальным монтажом без подключения платформ и AI. В зависимости от
    страны у вас могут быть права на доступ, исправление, удаление, ограничение обработки,
    возражение против неё или получение копии персональных данных. По сведениям у разработчика
    пишите на {CONTACT}; по данным у платформы обращайтесь к ней. Вы также можете иметь право
    обратиться в местный орган защиты данных.</p>
    <p>Проект не предназначен для детей младше 13 лет. Возрастные требования платформ также
    действуют. Если ребёнок отправил разработчику персональную информацию, сообщите об этом.</p>
    <p>Изменения практик обработки будут отражены здесь с новой датой. Политика описывает текущее
    приложение и не означает одобрения платформами или сертификации по определённому закону.</p>""",
    ),
]

TERMS_RU = [
    (
        "agreement",
        "1. Об этих условиях",
        f"""
    <p>Условия относятся к использованию приложения CLIP TRIBUNE и сайта проекта, который
    поддерживает {OWNER}. Контакт: {CONTACT}. Используя приложение, вы соглашаетесь с условиями.
    Если вы не согласны, не используйте его. Условия не отменяют ваши права по применимому закону.</p>
    <p>В <a href="privacy-ru.html">политике конфиденциальности</a> описаны локальное хранение,
    онлайн-функции и удаление данных. Вы должны иметь право заключить это соглашение либо
    необходимое по закону разрешение и сопровождение законного представителя.</p>""",
    ),
    (
        "service",
        "2. Возможности приложения",
        """
    <p>CLIP TRIBUNE — инструмент Windows для нарезки видео, разделённого экрана, наложения ваших
    материалов и необязательных интеграций скачивания и публикации. Монтаж выполняется на вашем
    компьютере. Сейчас приложение распространяется без платы за подписку.</p>
    <p>Где необходимо, вы предоставляете собственные ключи сервисов. У внешних провайдеров могут
    быть тарифы, квоты, требования к аккаунтам, проверке и региону. Разработчик не контролирует
    их доступность. Приложение не гарантирует непрерывную работу, успешную загрузку, одобрение API,
    монетизацию или определённую реакцию аудитории.</p>""",
    ),
    (
        "content",
        "3. Ваши материалы и ответственность",
        """
    <p>Вы сохраняете права на свои исходники и результат. Разработчик не заявляет право собственности
    на них. Используйте только видео, музыку, рекламу и другие материалы, которые вы вправе
    скачивать, изменять и публиковать. Публичная доступность видео сама по себе не даёт права на повторное использование.</p>
    <p>Вы отвечаете за необходимые согласия людей, достоверность описаний, авторские права и другие
    применимые требования. Перед публикацией проверяйте монтаж, субтитры и метаданные. Добавляйте
    необходимые обозначения рекламы, спонсорства и AI-контента.</p>
    <p>Не используйте приложение для нарушения прав, выдачи себя за другого человека, обмана,
    незаконного контента, спама, обхода ограничений доступа, платного доступа или технической защиты.
    Наличие функции не даёт разрешения на использование чужих материалов.</p>""",
    ),
    (
        "platforms",
        "4. Подключённые сервисы и публикация",
        """
    <p>Приложение использует YouTube API Services. Используя функции YouTube, вы соглашаетесь
    соблюдать <a href="https://www.youtube.com/t/terms">Условия использования YouTube</a>.
    Функции TikTok регулируются <a href="https://www.tiktok.com/legal/terms-of-service">условиями TikTok</a>
    для вашего региона и правилами публикации. Для Twitch действуют
    <a href="https://legal.twitch.com/en/legal/terms-of-service/">условия Twitch</a>.</p>
    <p>Вы поручаете приложению выполнять выбранные действия с подключёнными аккаунтами.
    Проверяйте аккаунт, видео и видимость до отправки или назначения задания. После загрузки
    черновика во входящие TikTok нужно завершить публикацию в TikTok. Прямая отправка зависит
    от разрешений и настроек, доступных через платформу.</p>
    <p>Остановка или отключение приложения не отменяет уже принятый платформой файл или готовую
    публикацию. Управляйте ими в соответствующем сервисе. CLIP TRIBUNE — независимый проект,
    не одобренный Google, YouTube, TikTok или Twitch.</p>""",
    ),
    (
        "software",
        "5. Программа, копии и сторонние компоненты",
        f"""
    <p>Сохраняйте резервные копии важных файлов и защищайте ключи. Вы управляете установкой,
    настройками и локальным хранилищем. Не распространяйте копии с персональными данными или секретами.</p>
    <p>Сторонние компоненты сохраняют свои лицензии, перечисленные в
    <a href="{REPO}/blob/main/docs/third-party-notices.txt">уведомлениях о компонентах</a>.
    Эти условия не заменяют и не ограничивают права, предоставленные такими лицензиями.</p>""",
    ),
    (
        "limits",
        "6. Доступность и ограничения",
        """
    <p>В пределах, разрешённых применимым законом, приложение предоставляется «как есть» и
    «по мере доступности», без гарантий пригодности для определённой задачи или безошибочной
    работы. Проверяйте результаты и делайте резервные копии перед использованием важных данных.</p>
    <p>В пределах, разрешённых законом, разработчик не отвечает за косвенные убытки, упущенную
    прибыль, потерю данных или действия платформ в отношении аккаунтов в связи с использованием
    приложения. Это не исключает ответственность и права потребителя, которые нельзя исключить по закону.</p>""",
    ),
    (
        "ending",
        "7. Прекращение использования и изменения",
        f"""
    <p>Вы можете прекратить использование в любое время, отозвать подключения и удалить локальные
    данные по <a href="privacy-ru.html#deletion">инструкции</a>. Разработчик может обновить или
    прекратить поддержку проекта. Условия могут изменяться с указанием новой даты. Проверяйте
    актуальную версию перед установкой обновлений или включением новых онлайн-функций.</p>
    <p>Вопросы об условиях или проекте: {CONTACT}.</p>""",
    ),
]


def layout(title, description, body, filename, lang="en"):
    """Единая шапка и подвал позволяют исправить навигацию сразу на всех страницах."""
    ru = lang == "ru"
    suffix = "-ru" if ru else ""
    links = [
        ("index.html", "О программе" if ru else "Overview"),
        (f"terms{suffix}.html", "Условия" if ru else "Terms"),
        (f"privacy{suffix}.html", "Конфиденциальность" if ru else "Privacy"),
    ]
    nav = "".join(
        f'<a href="{url}"' + (' aria-current="page"' if url == filename else "") + f">{label}</a>"
        for url, label in links
    )
    return f'''<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · CLIP TRIBUNE</title>
<meta name="description" content="{escape(description, quote=True)}">
<meta name="theme-color" content="#0c0d10">
<link rel="canonical" href="{SITE}{filename}">
<link rel="icon" href="site-assets/logo.svg" type="image/svg+xml">
<link rel="stylesheet" href="site.css"></head><body>
<a class="skip" href="#main">{"К содержимому" if ru else "Skip to content"}</a>
<header class="top"><div class="wrap"><a class="brand" href="index.html">
<img src="site-assets/logo.svg" width="38" height="38" alt="">CLIP TRIBUNE</a>
<nav class="nav" aria-label="{"Главная навигация" if ru else "Main navigation"}">{nav}</nav></div></header>
<main id="main">{body}</main>
<footer><div class="wrap"><span>CLIP TRIBUNE · {OWNER}</span>
<span>{CONTACT} · <a href="{REPO}">GitHub</a></span></div></footer></body></html>
'''


def legal_page(kind, lang, title, lead, sections):
    ru = lang == "ru"
    filename = kind + ("-ru" if ru else "") + ".html"
    other = kind + ("" if ru else "-ru") + ".html"
    toc = "".join(f'<a href="#{key}">{escape(heading)}</a>' for key, heading, _ in sections)
    article = "\n".join(
        f'<section id="{key}"><h2>{escape(heading)}</h2>{text}</section>' for key, heading, text in sections
    )
    body = f'''<div class="hero"><div class="wrap"><p class="eyebrow">CLIP TRIBUNE / Legal</p>
<h1>{escape(title)}</h1><p class="lead">{escape(lead)}</p><div class="meta">
<span>{"Дата вступления в силу" if ru else "Effective date"}: <time datetime="{DATE}">{DATE}</time></span>
<a href="{other}" lang="{"en" if ru else "ru"}" hreflang="{"en" if ru else "ru"}">{"English version" if ru else "Русская версия"}</a>
</div></div></div><div class="wrap document"><nav class="toc" aria-label="{"Содержание" if ru else "Contents"}">
<strong>{"На этой странице" if ru else "On this page"}</strong>{toc}</nav><article>{article}</article></div>'''
    (OUT / filename).write_text(layout(title, lead, body, filename, lang), encoding="utf-8")


def main():
    assets = OUT / "site-assets"
    assets.mkdir(exist_ok=True)
    for name in ("logo.svg", "logo.png"):
        shutil.copyfile(ROOT / "assets" / name, assets / name)
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    legal_page(
        "privacy",
        "en",
        "Privacy Policy",
        "Your media stays local unless you choose an online feature. Here is what is stored, sent and removable.",
        PRIVACY_EN,
    )
    legal_page(
        "terms",
        "en",
        "Terms of Service",
        "The terms for using CLIP TRIBUNE, your content and connected services.",
        TERMS_EN,
    )
    legal_page(
        "privacy",
        "ru",
        "Конфиденциальность",
        "Ваши медиа хранятся локально, пока вы не используете онлайн-функции. Здесь описано, что сохраняется, передаётся и удаляется.",
        PRIVACY_RU,
    )
    legal_page(
        "terms",
        "ru",
        "Условия использования",
        "Правила использования CLIP TRIBUNE, ваших материалов и подключённых сервисов.",
        TERMS_RU,
    )
    body = f'''<div class="hero"><div class="wrap"><p class="eyebrow">Windows / Local video studio</p>
<h1>Свои материалы.<br>Своя трибуна.</h1><p class="lead">CLIP TRIBUNE — локальная студия коротких видео.
Нарезка, два экрана, ваши рекламные вставки и отправка в YouTube и TikTok из одного приложения.</p>
<div class="actions"><a class="button primary" href="{REPO}/releases/latest">Скачать для Windows</a>
<a class="button" href="{REPO}#readme">Инструкция и исходники</a></div></div></div>
<div class="wrap"><div class="cards"><section class="card"><h2>Монтаж на компьютере</h2>
<p>FFmpeg обрабатывает видео локально. Для базового монтажа не нужны аккаунты и платная подписка.</p></section>
<section class="card"><h2>Публикация под контролем</h2><p>Вы выбираете аккаунт, ролик и настройки отправки.
Онлайн-интеграции требуют собственных ключей и разрешений платформ.</p></section>
<section class="card"><h2>Понятно о данных</h2><p>Читайте, что хранится локально, когда данные уходят
сервисам и как удалить свои подключения и файлы.</p><a href="privacy-ru.html">Политика конфиденциальности →</a></section></div>
<section class="home-detail" lang="en"><h2>About CLIP TRIBUNE</h2><p>A Windows desktop video editor
for short clips, split-screen compositions and user-provided overlays. Optional integrations upload
selected videos to YouTube and TikTok, subject to platform permissions. The app is maintained by
{OWNER} and is independent of those platforms.</p><p><a href="terms.html">Terms of Service</a> ·
<a href="privacy.html">Privacy Policy</a> · <a href="terms-ru.html" lang="ru">Условия на русском</a></p>
<p>Contact: {CONTACT}</p></section></div>'''
    (OUT / "index.html").write_text(
        layout(
            "Локальная студия видео",
            "CLIP TRIBUNE — студия коротких видео для Windows. Скачать приложение, прочитать инструкции и правила обработки данных.",
            body,
            "index.html",
            "ru",
        ),
        encoding="utf-8",
    )
    print("Created 5 pages in", OUT)


if __name__ == "__main__":
    main()
