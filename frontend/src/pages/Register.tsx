import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { registerUser, loginApi, me } from "../lib/api";
import { useAuth } from "../context/AuthContext";

const RegisterPage: React.FC = () => {
  const nav = useNavigate();
  const { login } = useAuth();
  const [form, setForm] = useState({ login: "", password: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await registerUser(form.login, form.password);
      const res = await loginApi(form.login, form.password);
      const profile = await me(res.access_token);
      login(res.access_token, profile);
      nav("/cameras", { replace: true });
    } catch (err: any) {
      setError(err?.message || "Ошибка регистрации");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="shell" style={{ maxWidth: 420 }}>
      <div className="card" style={{ marginTop: 60 }}>
        <h2 className="title">Регистрация</h2>
        <p className="muted" style={{ marginBottom: 16 }}>
          Создайте учётную запись (роль viewer). Администратор может повысить роль позже.
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
            {loading ? "Создаём..." : "Зарегистрироваться"}
          </button>
        </form>
        <div className="muted" style={{ marginTop: 8 }}>
          Уже есть учётка? <a href="/login">Войти</a>
        </div>
      </div>
    </div>
  );
};

export default RegisterPage;
