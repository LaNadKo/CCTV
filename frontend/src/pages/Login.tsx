import { useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { loginApi, me, getApiUrl, setApiUrl } from "../lib/api";
import { useAuth } from "../context/AuthContext";

const LoginPage: React.FC = () => {
  const { login } = useAuth();
  const nav = useNavigate();
  const location = useLocation();
  const from = (location.state as any)?.from?.pathname || "/cameras";
  const [form, setForm] = useState({ login: "", password: "" });
  const [totpCode, setTotpCode] = useState("");
  const [totpRequired, setTotpRequired] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastCreds, setLastCreds] = useState<{ login: string; password: string } | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await loginApi(form.login, form.password);
      const profile = await me(res.access_token);
      login(res.access_token, profile);
      nav(from, { replace: true });
    } catch (err: any) {
      if (err?.status === 400 && String(err?.message || "").toLowerCase().includes("totp")) {
        setTotpRequired(true);
        setLastCreds({ login: form.login, password: form.password });
      } else {
        setError(err?.message || "Ошибка входа");
      }
    } finally {
      setLoading(false);
    }
  };

  const submitTotp = async () => {
    if (!lastCreds) return;
    setLoading(true);
    setError(null);
    try {
      const res = await loginApi(lastCreds.login, lastCreds.password, totpCode || undefined);
      const profile = await me(res.access_token);
      login(res.access_token, profile);
      nav(from, { replace: true });
    } catch (err: any) {
      setError(err?.message || "Ошибка входа (TOTP)");
    } finally {
      setLoading(false);
      setTotpRequired(false);
      setTotpCode("");
    }
  };

  return (
    <div className="shell" style={{ maxWidth: 420 }}>
      <div className="card" style={{ marginTop: 60 }}>
        <h2 className="title">Вход в систему</h2>
        <p className="muted" style={{ marginBottom: 16 }}>
          Введите логин и пароль. Если включен TOTP — система запросит код.
        </p>
        <form className="stack" onSubmit={handleSubmit}>
          <label className="field">
            <span className="label">Логин</span>
            <input
              className="input"
              value={form.login}
              onChange={(e) => setForm({ ...form, login: e.target.value })}
              required
              autoFocus
            />
          </label>
          <label className="field">
            <span className="label">Пароль</span>
            <input
              className="input"
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              required
            />
          </label>
          {error && <div className="danger">{error}</div>}
          <button className="btn" type="submit" disabled={loading}>
            {loading ? "Входим..." : "Войти"}
          </button>
        </form>
        <div className="muted" style={{ marginTop: 8 }}>
          Нет учётки? <a href="/register">Регистрация</a>
        </div>
        <details style={{ marginTop: 12 }}>
          <summary className="muted" style={{ cursor: "pointer" }}>Настройка сервера</summary>
          <div className="field" style={{ marginTop: 8 }}>
            <span className="label">URL сервера</span>
            <input
              className="input"
              defaultValue={getApiUrl()}
              placeholder="https://cctv.example.com"
              onBlur={(e) => {
                const val = e.target.value.trim();
                if (val && val !== getApiUrl()) setApiUrl(val);
              }}
            />
            <span className="muted" style={{ fontSize: 12 }}>
              Укажите адрес вашего CCTV-сервера (например https://cctv.mydomain.ru)
            </span>
          </div>
        </details>
      </div>

      {totpRequired && (
        <div className="modal-backdrop">
          <div className="modal">
            <h3 style={{ marginTop: 0 }}>Введите TOTP</h3>
            <p className="muted">Эта учётка защищена TOTP. Введите код из приложения.</p>
            <div className="field" style={{ marginTop: 8 }}>
              <span className="label">TOTP код</span>
              <input
                className="input"
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value)}
                placeholder="123456"
              />
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" onClick={submitTotp} disabled={loading}>
                Подтвердить
              </button>
              <button className="btn secondary" onClick={() => setTotpRequired(false)}>
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default LoginPage;
