# P1-2 R1�CR4 �������������¼

���ڣ�2026-11-07�����ύ��8c4073975bc25c2b50ad2a18ee768ce6547080c8����֧��docs/p1-2-tool-lifecycle-design������ PR #3�����޸� main �� PR #1/#2��

## R1�CR4 ����

| Review | ԭ���� | �ĵ��޶� | �ĵ������� |
|---|---|---|---|
| R1 | ԭ�ľܾ�δ����ȡ���������ĵ�������ͼ/API/actor ��ͬ | ��3 �� PROPOSED��CANCELLED����3.1 ��������׶ξ������ط����ȼ�����4 CancelView/HTTP����5 ȡ���¼��ֶ��� actor | ͼ������API��payload �Ͳ��������������һ�� |
| R2 | ����ʧ�ܱ߽��豣�� | ��3.2 ���� FAILED_TO_START Ψһӳ�䣬��ȷ actor=system��claim ǰ��ִ���¼� | �� claim ���� dispatch_failed���޷�֤��δ���� UNKNOWN������ start ������ |
| R3 | ��ʱ/ȡ��/��Ȼ�˳�����ʵ���� | ��3.2 ���뵥��ʱ�䡢�˳�/��ֹ�������Լ�� timed_out �� reason | ��ͼ�����ڽ������Ȼ�˳�������ʵ exit code����ȷ�� UNKNOWN |
| R4 | ����¼�/������������Ƴ�ͻ | ������д ��8���滻 Mermaid�����¼�/schema/�ۼ�/gap��S01�CS08 �� ��10 ͬ�� | ֻ����һ�����־û���Լ�������� chunk ��д����Լ |

## ״̬�����¼���Լһ���Լ�飨��̬�ĵ��˶ԣ�

- PROPOSED ȡ����ͼ��ֱ�� CANCELLED������/API 200��payload tool_cancelled_before_start��actor=user��refs=proposed����������ִ���¼���
- APPROVED δ��ȡ��ͼֱ�� CANCELLED��200��ͬ�¼� actor=user��refs=approved���� execution��
- �� claim �����ɣ�ͼ APPROVED �Ի�����ͼ����202��tool_cancel_requested/user������ CAS �ܾ��� system ȷ�� before_start������ֱ�Ӽٶ���ֹͣ��
- �ѻ�����δ�տ�ʼ��ִ��202������ͼ��ȷ��δ spawn �� before_start������������ʵ started ����� RUNNING���޷�ȷ�� UNKNOWN��
- RUNNING��ͼ�Ի�����ͼ����202��ȡ������ֹ�� finished/tool/CANCELLED����Ȼ�˳� SUCCEEDED/FAILED��ʧ�� system/interrupted/UNKNOWN��
- ͬһȡ�����ԣ�ԭ HTTP/CancelView�����½��¼�����������������̬/UNKNOWN Ϊ 409����ԭ�����������طţ�GET ��ѯ����״̬��
- ���������ȡ���ʼ����ɵ�ԭʼ֤�ݱ߽籣����ȡ��������ٵ� started/finished��R2/R3 �Ѳ������ģ�������¼���ǽ��͡�
- ��ʽͼ���ڲ����ն�������� Event���־û��Ի���Ϊ model_stream_progress���ս���һ�� model_call���ɹ�����Ĭ��״̬��

## ���ݿ��������ݵ��Լ�飨��̬�ĵ��˶ԣ�

| ���� | Ψһ��� | ����/��ͻ |
|---|---|---|
| �û�д���� | challenge+principal+operation+key��ժҪ���� method��·����Դ ID��canonical body | ��ͬ�طţ����᰸/������ 409 |
| ȡ������ | ÿ proposal һ����Ч user ȡ����ͼ��ֱ��ȡ�������⣩��ȷ�����ж����¼� | ͬ�û�ͬ��Դ����������ͼ�������û����ɽ��� |
| ģ������ | batch_id PK��UNIQUE(request_id,first_sequence)��event_id UNIQUE���������� CHECK | ͬ batch/digest ���ԭ�¼������غɡ�ͬ first���ص����ܾ� |
| �ڲ�������� | request �� chunk_sequence���� 1 �������� | ����Ϊ DB ��������batch_first_sequence �������ֶ� |
| ȱ�� | gap_id PK��ͬ�� request/event FK | ��ȷ��Χ��δ֪β���������ɲ��������������� gap ������ |
| �ս� | request_id PK��terminal_event_id UNIQUE��CAS | ����һ�� model_call����ֹ�ڶ��ս���ս������ |

�� row/event/state/head ԭ�ӣ������ص���鲻�ܽ��������Ψһ���������� gap ���䲻�ܲ��������ս�ʵ�ʽ����������־ø������������ֱ���������ʧ�ӷ�����״̬ʱ���� null + �½� + unknown_tail������������ƶ�������

## ����ļ�������� Markdown��

1. docs/P1_TOOL_LIFECYCLE_DESIGN.md��ͳһ���ģ���3�C��5����6 ȡ��Լ������8����9����10���汾/���ã���
2. docs/P1_TOOL_LIFECYCLE_REVIEW_ADDENDUM.md���滻Ϊ���������ĵ� R1�CR4 ������
3. docs/P1_TOOL_LIFECYCLE_CONVERGENCE.md�����ζ��ռ�һ���Լ���¼��

## δʵ�֡�δ����

δ�������޸� Python/ǰ�˴��롢SQL Ǩ�ơ�ִ�нӿڻ�������ڡ�δִ����ʵ���߻�ģ�͵��ã�δӦ������ schema��δ���� S01�CS08/L/A/C ���ԣ�Ҳδ��֤ SQLite ������������ʱ��API ���ء��޶����ܻ���ϻָ���Mermaid ����Դ�ı��ṹ�˶ԣ�δ����Ⱦ����֤�����������һ�¡���Ϊ�ĵ������ۣ��������в���ͨ����

PR ����ͬ�����£����� Draft���ȴ��������գ����ֲ���Ȩʵʩ��ϲ���
