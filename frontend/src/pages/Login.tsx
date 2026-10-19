import { useState } from 'react'
import { Input, Button, Checkbox, message } from 'antd'
import { UserOutlined, LockOutlined, CloudFilled } from '@ant-design/icons'
import { api } from '../api'

export default function Login({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [loading, setLoading] = useState(false)

  async function submit() {
    if (!username.trim() || !password) { message.warning('请输入账号和密码'); return }
    setLoading(true)
    try {
      await api.login(username.trim(), password)
      onSuccess()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '登录失败')
    } finally { setLoading(false) }
  }
  const todo = () => message.info('请联系管理员')

  return (
    <div className="login-wrap">
      <div className="login-left">
        <div className="login-logo"><CloudFilled style={{ color: '#2468f2' }} /> 百度智能云</div>
        <div className="cloud-art">
          <div className="cloud-s a s1" />
          <div className="cloud-s b s1" />
          <div className="cloud-main" />
        </div>
        <h1>文档抽取评测平台</h1>
        <div className="login-grad">智 能 · 高 效 · 可 依 赖</div>
        <div className="login-desc">
          基于百度智能云 OCR 与文档抽取能力，提供一站式文档解析、抽取与效果评测服务，让每一份数据都精准可信。
        </div>
        <div className="login-pills">
          <span className="login-pill">通用文字识别</span>
          <span className="login-pill">卡证票据</span>
          <span className="login-pill">多模态解析</span>
        </div>
      </div>

      <div className="login-right">
        <div className="login-card">
          <h2>欢迎登录</h2>
          <div className="sub">请使用平台账号登录，开启文档抽取评测之旅</div>

          <div className="login-field-label">账号</div>
          <Input className="input" size="large" prefix={<UserOutlined style={{ color: '#9aa4b8' }} />}
            placeholder="请输入账号 / 邮箱" value={username}
            onChange={e => setUsername(e.target.value)} onPressEnter={submit} />

          <div className="login-field-label">密码</div>
          <Input.Password className="input" size="large" prefix={<LockOutlined style={{ color: '#9aa4b8' }} />}
            placeholder="请输入密码" value={password}
            onChange={e => setPassword(e.target.value)} onPressEnter={submit} />

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '16px 0 20px' }}>
            <Checkbox checked={remember} onChange={e => setRemember(e.target.checked)}>记住我</Checkbox>
            <span className="login-link" onClick={todo}>忘记密码?</span>
          </div>

          <Button className="btn" type="primary" size="large" block loading={loading} onClick={submit}
            style={{ height: 46, fontSize: 16, letterSpacing: 4 }}>登 录</Button>

          <div className="login-divider">其他方式</div>
          <div className="login-foot">还没有账号？<span className="login-link" onClick={todo}>立即注册</span></div>
        </div>
      </div>
    </div>
  )
}
