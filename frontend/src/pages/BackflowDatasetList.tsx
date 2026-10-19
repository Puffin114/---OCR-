import { useEffect, useState } from 'react'
import { Button, Card, Table, Space, message, Popconfirm, Empty } from 'antd'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

export default function BackflowDatasetList() {
  const [datasets, setDatasets] = useState<any[]>([])
  const nav = useNavigate()

  const refresh = () => api.listBackflowDatasets().then(setDatasets).catch(() => { })
  useEffect(() => { refresh() }, [])

  async function remove(id: number) {
    try {
      await api.deleteDataset(id)
      message.success('已删除回流数据集')
      refresh()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || String(e))
    }
  }

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Button type="primary" onClick={() => nav('/backflow')}>回流数据</Button>
        <Button onClick={() => nav('/datasets')}>返回数据集</Button>
        <span style={{ color: '#999' }}>这里仅展示通过「回流数据」从业务库回流的数据集</span>
      </Space>
      <Card title="回流数据集列表">
        {datasets.length === 0
          ? <Empty description="暂无回流数据集，点击「回流数据」从业务库回流" />
          : <Table rowKey="id" dataSource={datasets} pagination={false}
            columns={[
              { title: 'ID', dataIndex: 'id', width: 60 },
              { title: '名称', dataIndex: 'name' },
              { title: '文档数', dataIndex: 'doc_total', width: 100 },
              { title: '创建时间', dataIndex: 'created_at', width: 180 },
              {
                title: '操作', width: 360, render: (_, r) => (
                  <Space>
                    <Button size="small" onClick={() => nav(`/datasets/${r.id}/annotate`)}>二次标注</Button>
                    <Button size="small" type="primary" onClick={() => nav(`/datasets/${r.id}/new-task`)}>新建评测任务</Button>
                    <Popconfirm title="确认删除该回流数据集？" description="将一并删除其标注、评测任务与回流文件，不可恢复。"
                      okText="删除" cancelText="取消" okButtonProps={{ danger: true }}
                      onConfirm={() => remove(r.id)}>
                      <Button size="small" danger>删除</Button>
                    </Popconfirm>
                  </Space>
                )
              },
            ]} />}
      </Card>
    </div>
  )
}
