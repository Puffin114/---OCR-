import ReactECharts from 'echarts-for-react'

interface Series { name: string; data: number[] }
interface Props {
  title?: string
  categories: string[]
  series: Series[]
  colors?: string[]
}

const DEFAULT_COLORS = ['#2468f2', '#36c361', '#ff9f40', '#9b5cf6', '#ff6b6b']

export default function MetricBarChart({ title, categories, series, colors }: Props) {
  const option = {
    title: title ? { text: title, left: 0, textStyle: { fontSize: 13, color: '#333' } } : undefined,
    color: colors || DEFAULT_COLORS,
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${v}%` },
    legend: { top: 0, type: 'scroll' },
    grid: { top: title ? 56 : 40, left: 48, right: 16, bottom: 30 },
    xAxis: { type: 'category', data: categories, axisLabel: { color: '#666' } },
    yAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value} %', color: '#999' } },
    series: series.map(s => ({
      name: s.name, type: 'bar', data: s.data, barMaxWidth: 48,
      label: { show: true, position: 'inside', formatter: (p: any) => `${p.value}%`, fontSize: 10 },
    })),
  }
  return <ReactECharts option={option} style={{ height: 300 }} notMerge />
}
