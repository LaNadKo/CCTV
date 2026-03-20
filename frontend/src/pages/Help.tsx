const HelpPage: React.FC = () => {
  return (
    <div className="stack" style={{ marginTop: 18 }}>
      <section className="toolbar-card">
        <div className="stack" style={{ gap: 4 }}>
          <h2 className="title">Справка</h2>
          <div className="muted">Краткая сводка по работе Console, backend и Processor.</div>
        </div>
      </section>

      <section className="grid">
        <article className="panel-card stack">
          <h3 className="panel-card__title">Авторизация и backend</h3>
          <div className="muted">
            Console подключается к backend по адресу из настроек. После первого входа можно сохранить адрес сервера,
            тему и состав навигации, а затем продолжить работу без повторной настройки.
          </div>
        </article>

        <article className="panel-card stack">
          <h3 className="panel-card__title">Live и Review</h3>
          <div className="muted">
            Живой поток, review и архив строятся через Processor. Если live недоступен, сначала проверьте назначение
            камеры на Processor и его текущий статус.
          </div>
        </article>

        <article className="panel-card stack">
          <h3 className="panel-card__title">Записи и снимки</h3>
          <div className="muted">
            Медиа хранится на Processor и открывается через backend-прокси. В архиве доступны лента дня, почасовой
            обзор и минутные клипы с маркерами событий.
          </div>
        </article>

        <article className="panel-card stack">
          <h3 className="panel-card__title">Processor</h3>
          <div className="muted">
            Processor выполняет детект, распознавание, body-track и формирование медиа. Backend хранит метаданные,
            пользователей, отчёты и проксирует доступ к медиа.
          </div>
        </article>
      </section>
    </div>
  );
};

export default HelpPage;
