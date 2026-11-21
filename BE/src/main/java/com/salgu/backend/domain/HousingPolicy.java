package com.salgu.backend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import java.time.LocalDate;
import java.time.LocalDateTime;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.Immutable;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Getter
@Entity
@Immutable
@Table(name = "housing_policies")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class HousingPolicy extends SourceRowEntity {

    private String plcyNo;

    private String bscPlanCycl;

    private String bscPlanPlcyWayNo;

    private String bscPlanFcsAsmtNo;

    private String bscPlanAsmtNo;

    private String pvsnInstGroupCd;

    private String plcyPvsnMthdCd;

    private String plcyAprvSttsCd;

    private String plcyNm;

    private String plcyKywdNm;

    private String plcyExplnCn;

    private String lclsfNm;

    private String mclsfNm;

    private String plcySprtCn;

    private String sprvsnInstCd;

    private String sprvsnInstCdNm;

    private String sprvsnInstPicNm;

    private String operInstCd;

    private String operInstCdNm;

    private String operInstPicNm;

    private String sprtSclLmtYn;

    private String aplyPrdSeCd;

    private String bizPrdSeCd;

    private LocalDate bizPrdBgngYmd;

    private LocalDate bizPrdEndYmd;

    private String bizPrdEtcCn;

    private String plcyAplyMthdCn;

    private String srngMthdCn;

    private String aplyUrlAddr;

    private String sbmsnDcmntCn;

    private String etcMttrCn;

    @Column(name = "ref_url_addr1")
    private String refUrlAddr1;

    @Column(name = "ref_url_addr2")
    private String refUrlAddr2;

    private Integer sprtSclCnt;

    private String sprtArvlSeqYn;

    private Integer sprtTrgtMinAge;

    private Integer sprtTrgtMaxAge;

    private String sprtTrgtAgeLmtYn;

    private String mrgSttsCd;

    private String earnCndSeCd;

    private String earnMinAmt;

    private String earnMaxAmt;

    private String earnEtcCn;

    private String addAplyQlfcCndCn;

    private String ptcpPrpTrgtCn;

    private Integer inqCnt;

    private String rgtrInstCd;

    private String rgtrInstCdNm;

    private String rgtrUpInstCd;

    private String rgtrUpInstCdNm;

    private String rgtrHghrkInstCd;

    private String rgtrHghrkInstCdNm;

    private String zipCd;

    private String plcyMajorCd;

    private String jobCd;

    private String schoolCd;

    private String aplyYmd;

    private LocalDateTime frstRegDt;

    private LocalDateTime lastMdfcnDt;

    private String sbizCd;

    private String regionClassification;

    @JdbcTypeCode(SqlTypes.JSON)
    private String rawPayload;
}
