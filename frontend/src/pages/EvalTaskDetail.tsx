import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Tabs, Descriptions, Tag, Button, Space, Table, Segmented, message, Empty, Alert, Modal, Input, Tooltip } from 'antd'
import { api } from '../api'
import MetricBarChart from '../components/MetricBarChart'

const STATUS: Record<string, any> = {
  running: <Tag color="processing">评测中</Tag>,
  success: <Tag color="success">评测成功</Tag>,
  failed: <Tag color="error">评测失败</Tag>,
  created: <Tag>已创建</Tag>,
}

export default function EvalTaskDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const [task, setTask] = useState<any>(null)
  const [metrics, setMetrics] = useState<any>(null)
  const [detailExpand, setDetailExpand] = useState(false)
  const [bucket, setBucket] = useState<'original' | 'reviewed'>('original')
  const [perf, setPerf] = useState<any>(null)
  const [preds, setPreds] = useState<any>(null)
  const [renameOpen, setRenameOpen] = useState(false)
  const [renameValue, setRenameValue] = useState('')

  const load = () => {
    api.getEvalTask(Number(id)).then(setTask)
    api.getMetrics(Number(id)).then(setMetrics).catch(() => setMetrics(null))
    api.getPerformance(Number(id)).then(setPerf).catch(() => setPerf(null))
    api.taskPredictions(Number(id)).then(setPreds).catch(() => setPreds(null))
  }
  useEffect(() => {
    load()
    const t = setInterval(() => { if (task?.status === 'running') load() }, 4000)
    return () => clearInterval(t)
    // eslint-disable-next-line
  }, [id, task?.status])

  if (!task) return null

  const hasReviewed = metrics?.reviewed?.overall
  const versions: { key: 'original' | 'reviewed'; name: string }[] = [{ key: 'original', name: '原始' }]
  if (hasReviewed) versions.push({ key: 'reviewed', name: '人工复核后' })

  const overallSeries = versions.map(v => ({
    name: v.name,
    data: [metrics?.[v.key]?.overall?.precision ?? 0,
    metrics?.[v.key]?.overall?.recall ?? 0,
    metrics?.[v.key]?.overall?.f1 ?? 0],
  }))
  // 子字段紧跟母字段成组：按 (parent ?? field) 首次出现顺序分组后展开
  const orderItems = (items: any[]) => {
    const groups: string[] = []
    const byGroup: Record<string, any[]> = {}
    for (const it of items || []) {
      const g = it.parent || it.field
      if (!byGroup[g]) { byGroup[g] = []; groups.push(g) }
      byGroup[g].push(it)
    }
    return groups.flatMap(g => byGroup[g])
  }
  const orderedOriginal = orderItems(metrics?.original?.fields || [])
  const fields = orderedOriginal.map((f: any) => f.field)
  const detailSeries = (metricName: 'precision' | 'recall' | 'f1') => versions.map(v => ({
    name: v.name,
    data: fields.map((fn: string) =>
      (metrics?.[v.key]?.fields || []).find((x: any) => x.field === fn)?.[metricName] ?? 0),
  }))

  const curBucket = hasReviewed ? bucket : 'original'
  const bucketData = metrics?.[curBucket]
  const overallRow = bucketData?.overall
    ? { key: 'overall', name: '全数据集', data_count: bucketData.overall.data_count,
        precision: bucketData.overall.precision, recall: bucketData.overall.recall, f1: bucketData.overall.f1 }
    : null
  const fieldRows = orderItems(bucketData?.fields || []).map((f: any) => ({
    key: f.field, name: f.parent ? `　└ ${f.field}` : f.field, ...f }))
  const detailRows = overallRow ? (detailExpand ? [overallRow, ...fieldRows] : [overallRow]) : []

  const failItems = (preds?.items || []).filter((x: any) => x.status !== 'ok')
  const predWarning = preds && (preds.error_count > 0 || preds.empty_count > 0) ? (
    <Alert type="warning" showIcon style={{ marginBottom: 12 }}
      message={`检测到 ${failItems.length}/${preds.total} 篇文档抽取未产生有效预测，指标因此偏低或为 0（标注数据正常）`}
      description={
        <div style={{ fontSize: 12 }}>
          {failItems.slice(0, 10).map((x: any) => (
            <div key={x.doc_key}>· {x.doc_key}：{x.status === 'failed' ? (x.error || '抽取失败') : '预测为空'}</div>
          ))}
          <div style={{ marginTop: 6, color: '#999' }}>
            如为公有云接口报错，可在 config.yaml 核对 submit_url/result_url。
          </div>
        </div>
      } />
  ) : null

  const perfOverall = perf?.overall
  const performanceCard = (
    <Card size="small" title="性能指标" style={{ marginBottom: 16 }}>
      <Table rowKey="scope" size="small" pagination={false}
        dataSource={perfOverall ? [{ scope: '全数据集', ...perfOverall }] : []}
        columns={[
          { title: '数据集', dataIndex: 'scope' },
          { title: '文件数', dataIndex: 'doc_count', width: 90 },
          { title: '切片数', dataIndex: 'slice_count', width: 90 },
          { title: '抽取平均耗时（切片）', dataIndex: 'avg_per_slice_ms', width: 180, render: v => `${v} ms` },
          { title: '抽取平均耗时（文件）', dataIndex: 'avg_per_file_ms', width: 180, render: v => `${v} ms` },
        ]} />
    </Card>
  )

  const metricsTab = (
    <div>
      <Space style={{ marginBottom: 8 }}>
        <b>端到端效果</b>
        <Tooltip title={task.status !== 'success' ? '评测完成后可查看' : ''}>
          <Button type="link" disabled={task.status !== 'success'}
            onClick={() => nav(`/tasks/${id}/result`)}>查看评测结果 →</Button>
        </Tooltip>
      </Space>
      <div style={{ marginBottom: 12 }}>
        <Tag color="geekblue">测试接口：{task.engine || '未记录'}</Tag>
      </div>
      {predWarning}
      {!metrics?.original?.overall ? (
        <Empty description={task.status === 'running' ? '评测进行中，请稍候…' : '暂无指标'} />
      ) : (
        <>
          {/* ① 综合指标：柱状图 */}
          <Card size="small" title="综合指标" style={{ marginBottom: 16 }}>
            <MetricBarChart categories={['准确率', '召回率', 'F1-Score']} series={overallSeries} />
          </Card>

          {/* ② 详细指标：表格 + 展开各字段 */}
          <Card size="small" style={{ marginBottom: 16 }} title={
            <Space>
              详细指标
              {hasReviewed && (
                <Segmented size="small" value={bucket} onChange={v => setBucket(v as any)}
                  options={versions.map(v => ({ label: v.name, value: v.key }))} />
              )}
              <Button type="link" size="small" onClick={() => setDetailExpand(e => !e)}>
                {detailExpand ? '收起各字段' : '展开各字段'}</Button>
            </Space>
          }>
            <Table rowKey="key" size="small" pagination={false} dataSource={detailRows}
              columns={[
                { title: '名称', dataIndex: 'name' },
                { title: '数据量', dataIndex: 'data_count', width: 90 },
                { title: '准确率', dataIndex: 'precision', width: 110, render: v => `${v}%` },
                { title: '召回率', dataIndex: 'recall', width: 110, render: v => `${v}%` },
                { title: 'F1-Score', dataIndex: 'f1', width: 110, render: v => `${v}%` },
              ]} />
          </Card>

          {/* ③ 性能指标：综合表格 */}
          {performanceCard}

          {/* ④ 可视化图表：各字段柱状图 */}
          <Card size="small" title="可视化图表（各字段）" style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 12, color: '#999', margin: '4px 0' }}>各字段 · 准确率</div>
            <MetricBarChart categories={fields} series={detailSeries('precision')} />
            <div style={{ fontSize: 12, color: '#999', margin: '12px 0 4px' }}>各字段 · 召回率</div>
            <MetricBarChart categories={fields} series={detailSeries('recall')} />
            <div style={{ fontSize: 12, color: '#999', margin: '12px 0 4px' }}>各字段 · F1-Score</div>
            <MetricBarChart categories={fields} series={detailSeries('f1')} />
          </Card>
        </>
      )}
    </div>
  )

  const infoTab = (
    <div>
      <div style={{ fontWeight: 600, margin: '4px 0 10px' }}>基本信息</div>
      <Descriptions bordered column={3} size="small" style={{ marginBottom: 20 }}>
        <Descriptions.Item label="任务名称">{task.name}</Descriptions.Item>
        <Descriptions.Item label="任务ID">eval-{task.id}</Descriptions.Item>
        <Descriptions.Item label="创建人">本地</Descriptions.Item>
        <Descriptions.Item label="创建时间">{task.created_at || '-'}</Descriptions.Item>
        <Descriptions.Item label="评测服务">{task.engine || '未记录'}</Descriptions.Item>
        <Descriptions.Item label="启动方式">立即启动</Descriptions.Item>
        <Descriptions.Item label="启动时间">{task.started_at || '-'}</Descriptions.Item>
        <Descriptions.Item label="结束时间">{task.finished_at || '-'}</Descriptions.Item>
        <Descriptions.Item label="状态">{STATUS[task.status]}</Descriptions.Item>
      </Descriptions>

      <div style={{ fontWeight: 600, margin: '4px 0 10px' }}>评测配置</div>
      <Descriptions bordered column={3} size="small" style={{ marginBottom: 20 }}>
        <Descriptions.Item label="评测场景">{task.engine || '未记录'}</Descriptions.Item>
        <Descriptions.Item label="版本">{task.version}</Descriptions.Item>
      </Descriptions>

      <div style={{ fontWeight: 600, margin: '4px 0 10px' }}>评测数据集</div>
      <Table rowKey="name" size="small" pagination={false}
        dataSource={task.dataset_name ? [{ name: task.dataset_name, total: task.doc_keys?.length ?? task.dataset_total }] : []}
        columns={[
          { title: '数据集名称', dataIndex: 'name' },
          { title: '数据量', dataIndex: 'total', width: 160 },
        ]} />
    </div>
  )

  return (
    <Card title={<Space>{task.name} {STATUS[task.status]}</Space>}
      extra={
        <Space>
          <Button onClick={() => { setRenameValue(task.name); setRenameOpen(true) }}>重命名</Button>
          <Button onClick={() => nav(`/datasets/${task.dataset_id}/new-task?copyFrom=${task.id}`)}>复制任务</Button>
          <Button danger onClick={async () => { await api.deleteEvalTask(task.id); message.success('已删除'); nav('/tasks') }}>删除</Button>
        </Space>
      }>
      <Tabs items={[
        { key: 'info', label: '任务详情', children: infoTab },
        { key: 'metrics', label: '评测指标', children: metricsTab },
      ]} />
      <Modal open={renameOpen} title="重命名任务" okText="保存" cancelText="取消"
        onCancel={() => setRenameOpen(false)}
        onOk={async () => {
          const name = renameValue.trim()
          if (!name) { message.warning('名称不能为空'); return }
          await api.renameEvalTask(task.id, name)
          setRenameOpen(false)
          message.success('已重命名')
          load()
        }}>
        <Input value={renameValue} onChange={e => setRenameValue(e.target.value)}
          onPressEnter={() => { /* 回车交给 onOk 按钮 */ }} placeholder="输入新的任务名称" />
      </Modal>
    </Card>
  )
}
