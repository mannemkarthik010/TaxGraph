"use client";

import { PageHeader } from "@/components/tp/primitives";
import { ExaminerMode } from "@/components/tp/filing/examiner";

export default function ExaminerPage() {
  return (
    <div>
      <PageHeader title="Examiner Mode" subtitle="The filed return, reconstructed and defended: reported amount, evidence, calculation, adjustments, verification, judgment and filed result for any item." />
      <ExaminerMode />
    </div>
  );
}
