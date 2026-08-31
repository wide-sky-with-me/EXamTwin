import { Breadcrumb, Button, Card, Col, Flex, Result, Row, Space, Tag, Typography } from "antd";
import { FileText, Files, LibraryBig } from "lucide-react";
import { useNavigate, useParams } from "react-router";

import { paperIndexPath, subjectWorkspacePath } from "../lib/paper-routes";
import type { SubjectStatus } from "../types";

const { Text, Title } = Typography;

export function SubjectOverview({ subjects }: { subjects: SubjectStatus[] }) {
  const navigate = useNavigate();
  const { subjectId = "" } = useParams();
  const subject = subjects.find((item) => item.id === subjectId);
  if (!subject) {
    return <Result status="404" title="科目不存在" subTitle="该 URL 中的科目标识无效或科目已被删除。" extra={<Button onClick={() => navigate("/subjects")} type="primary">返回科目列表</Button>} />;
  }
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Breadcrumb items={[{ title: "科目" }, { title: subject.title }]} />
      <Flex align="center" justify="space-between" wrap gap="middle">
        <Space direction="vertical" size={0}>
          <Space wrap>
            <Tag color="blue">{subject.subject_code}</Tag>
            <Text type="secondary">{subject.board_name}</Text>
          </Space>
          <Title level={2} style={{ margin: 0 }}>{subject.title}</Title>
        </Space>
        <Button onClick={() => navigate(paperIndexPath(subject.id))} size="large" type="primary">进入试卷库</Button>
      </Flex>
      <Row gutter={[16, 16]}>
        <Col lg={8} md={12} xs={24}>
          <Card actions={[<Button key="documents" onClick={() => navigate(subjectWorkspacePath(subject.id, "documents"))} type="link">管理资料</Button>]}>
            <Card.Meta avatar={<Files size={24} />} title="资料库" description="大纲、教材、Question Paper、Mark Scheme 与 Source Booklet。" />
          </Card>
        </Col>
        <Col lg={8} md={12} xs={24}>
          <Card actions={[<Button key="knowledge" onClick={() => navigate(subjectWorkspacePath(subject.id, "knowledge"))} type="link">查看知识库</Button>]}>
            <Card.Meta avatar={<LibraryBig size={24} />} title="知识库" description="维护授权资料并构建当前科目的可检索知识版本。" />
          </Card>
        </Col>
        <Col lg={8} md={12} xs={24}>
          <Card actions={[<Button key="papers" onClick={() => navigate(paperIndexPath(subject.id))} type="link">打开试卷库</Button>]}>
            <Card.Meta avatar={<FileText size={24} />} title="试卷库" description="管理严格配对的试卷、评分标准和支撑材料。" />
          </Card>
        </Col>
      </Row>
    </Space>
  );
}
