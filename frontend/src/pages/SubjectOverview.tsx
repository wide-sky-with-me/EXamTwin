import { Breadcrumb, Button, Card, Col, Result, Row, Statistic, Typography } from "antd";
import { Files, LibraryBig } from "lucide-react";
import { useNavigate, useParams } from "react-router";

import { paperIndexPath, subjectWorkspacePath } from "../lib/paper-routes";
import type { SubjectStatus } from "../types";

export function SubjectOverview({ subjects }: { subjects: SubjectStatus[] }) {
  const navigate = useNavigate();
  const { subjectId = "" } = useParams();
  const subject = subjects.find((item) => item.id === subjectId);
  if (!subject) {
    return <Result status="404" title="科目不存在" extra={<Button onClick={() => navigate("/subjects")} type="primary">返回科目列表</Button>} />;
  }
  const entries: { key: string; icon: typeof Files; title: string; value: number; suffix?: string; action: string; path: string }[] = [
    {
      key: "documents",
      icon: Files,
      title: "资料库",
      value: subject.stats?.documents_total ?? 0,
      action: "管理资料",
      path: subjectWorkspacePath(subject.id, "documents"),
    },
    {
      key: "knowledge",
      icon: LibraryBig,
      title: "知识库",
      value: subject.vector_points,
      suffix: "向量",
      action: "查看知识库",
      path: subjectWorkspacePath(subject.id, "knowledge"),
    },
  ];
  return (
    <div className="subject-overview-page">
      <Breadcrumb items={[{ title: <a onClick={() => navigate("/subjects")}>科目</a> }, { title: subject.title }]} />
      <header className="catalog-page-header">
        <div className="catalog-page-heading">
          <Typography.Title className="catalog-page-title" level={1}>{subject.title}</Typography.Title>
        </div>
        <Button className="catalog-primary-action" onClick={() => navigate(paperIndexPath(subject.id))} type="primary">进入试卷库</Button>
      </header>
      <Row gutter={[16, 16]}>
        {entries.map(({ key, icon: Icon, title, value, suffix, action, path }) => (
          <Col key={key} md={12} xs={24}>
            <Card actions={[<Button key={key} onClick={() => navigate(path)} type="link">{action}</Button>]}>
              <Statistic prefix={<Icon size={18} />} suffix={suffix} title={title} value={value} />
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}
