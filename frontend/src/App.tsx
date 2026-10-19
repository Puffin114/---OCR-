import { useEffect, useState } from 'react'
import { Routes, Route, NavLink, Navigate } from 'react-router-dom'
import { Button, Spin, ConfigProvider } from 'antd'
import DatasetList from './pages/DatasetList'
import CreateDataset from './pages/CreateDataset'
import Backflow from './pages/Backflow'
import BackflowDatasetList from './pages/BackflowDatasetList'
import Annotate from './pages/Annotate'
import EvalTaskList from './pages/EvalTaskList'
import EvalTaskPreview from './pages/EvalTaskPreview'
import EvalTaskDetail from './pages/EvalTaskDetail'
import EvalResult from './pages/EvalResult'
import Settings from './pages/Settings'
import Login from './pages/Login'
import { api } from './api'

const THEME = { token: { colorPrimary: '#2468f2', borderRadius: 8, borderRadiusLG: 10 } }

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null)

  // 每次页面加载/刷新都强制重新登录：先清掉可能残留的会话再置为未登录，
  // 这样刷新或直接输入子页面 URL 都会先回到登录页（所有路由都在 authed 之后才渲染）。
  useEffect(() => {
    api.logout().catch(() => { /* 无会话时忽略 */ }).finally(() => setAuthed(false))
    const onUnauth = () => setAuthed(false)
    window.addEventListener('app-unauthorized', onUnauth)
    return () => window.removeEventListener('app-unauthorized', onUnauth)
  }, [])

  async function logout() {
    try { await api.logout() } catch { /* ignore */ }
    setAuthed(false)
  }

  let body: JSX.Element
  if (authed === null) {
    body = <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Spin /></div>
  } else if (!authed) {
    body = <Login onSuccess={() => setAuthed(true)} />
  } else {
    body = (
      <div>
        <div className="topnav">
          <span className="brand">文档抽取评测平台</span>
          <NavLink to="/datasets" className={({ isActive }) => (isActive ? 'active' : '')}>数据集</NavLink>
          <NavLink to="/tasks" className={({ isActive }) => (isActive ? 'active' : '')}>评测任务</NavLink>
          <NavLink to="/settings" className={({ isActive }) => (isActive ? 'active' : '')}>配置中心</NavLink>
          <span style={{ flex: 1 }} />
          <Button size="small" onClick={logout}>退出登录</Button>
        </div>
        <div className="page">
          <Routes>
            <Route path="/" element={<Navigate to="/datasets" replace />} />
            <Route path="/datasets" element={<DatasetList />} />
            <Route path="/datasets/create" element={<CreateDataset />} />
            <Route path="/backflow" element={<Backflow />} />
            <Route path="/backflow/datasets" element={<BackflowDatasetList />} />
            <Route path="/datasets/:id/annotate" element={<Annotate />} />
            <Route path="/datasets/:id/new-task" element={<EvalTaskPreview />} />
            <Route path="/tasks" element={<EvalTaskList />} />
            <Route path="/tasks/:id" element={<EvalTaskDetail />} />
            <Route path="/tasks/:id/result" element={<EvalResult />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </div>
      </div>
    )
  }

  return <ConfigProvider theme={THEME}>{body}</ConfigProvider>
}

