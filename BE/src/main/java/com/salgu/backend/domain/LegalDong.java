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
@Table(name = "legal_dongs")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class LegalDong extends SourceRowEntity {

    private String legalDongCode;

    private String legalDongName;

    private String status;
}
