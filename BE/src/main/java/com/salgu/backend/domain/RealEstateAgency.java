package com.salgu.backend.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.Immutable;

@Getter
@Entity
@Immutable
@Table(name = "real_estate_agencies")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class RealEstateAgency extends SourceRowEntity {

    private String systemId;

    private String districtCode;

    private String legalDongCode;

    private String districtName;

    private String legalDongName;

    private String lotType;

    private String mainLotNo;

    private String subLotNo;

    private String address;

    private String registrationNo;

    private String agentName;

    private String agencyName;

    private String phone;

    private String status;

    private Long sourceQueryCount;

    private String roadCode;

    private String buildingFlag;

    private String buildingMainNo;

    private String buildingSubNo;
}
